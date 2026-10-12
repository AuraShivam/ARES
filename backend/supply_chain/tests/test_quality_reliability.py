import hashlib
import os
import xml.etree.ElementTree as ET
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from config.api_errors import api_exception_handler
from supply_chain.gdacs_feed import FEED_KEY, sync_gdacs_alerts
from supply_chain.models import (
    Disruption,
    ExternalFeed,
    ExternalFeedEvent,
    NotificationDelivery,
    ResponseAction,
    ResponseActionExecution,
    ResponsePlan,
    RiskAlert,
    RiskAssessmentSnapshot,
    RiskOutcome,
)
from supply_chain.notifications import dispatch_notifications
from supply_chain.risk_workflow import assess_and_record


User = get_user_model()


def _gdacs_item():
    document = ET.fromstring(
        """<rss><channel><item>
        <eventtype>EQ</eventtype><eventid>ARES-TEST-42</eventid><episodeid>1</episodeid>
        <alertlevel>orange</alertlevel><eventname>Test earthquake</eventname>
        <country>Test region</country><pubdate>2026-10-12T00:00:00Z</pubdate>
        <description>Test source event</description><link>https://example.org/event</link>
        </item></channel></rss>"""
    )
    return document.find("channel").findall("item")


class FeedReliabilityTests(APITestCase):
    def test_failed_sync_can_retry_and_duplicate_source_event_is_idempotent(self):
        with patch.dict(os.environ, {
            "ARES_GDACS_MIN_ALERT_LEVEL": "orange",
            "ARES_GDACS_POLL_INTERVAL_SECONDS": "360",
        }):
            with patch("supply_chain.gdacs_feed._fetch_feed_items", side_effect=RuntimeError("temporary upstream error")):
                with self.assertRaisesRegex(RuntimeError, "temporary upstream error"):
                    sync_gdacs_alerts()

            feed = ExternalFeed.objects.get(key=FEED_KEY)
            self.assertEqual(feed.status, "failed")
            self.assertEqual(feed.consecutive_failures, 1)

            feed.last_attempt_at = timezone.now() - timedelta(minutes=7)
            feed.save(update_fields=["last_attempt_at"])
            with patch("supply_chain.gdacs_feed._fetch_feed_items", return_value=_gdacs_item()):
                first = sync_gdacs_alerts()

            self.assertEqual(first["counts"]["created"], 1)
            self.assertEqual(ExternalFeedEvent.objects.filter(feed=feed).count(), 1)
            self.assertEqual(Disruption.objects.filter(source_key="GDACS:EQ:ARES-TEST-42:1").count(), 1)
            self.assertEqual(RiskAssessmentSnapshot.objects.count(), 1)

            feed.refresh_from_db()
            feed.last_attempt_at = timezone.now() - timedelta(minutes=7)
            feed.save(update_fields=["last_attempt_at"])
            with patch("supply_chain.gdacs_feed._fetch_feed_items", return_value=_gdacs_item()):
                retry = sync_gdacs_alerts()

        self.assertEqual(retry["counts"]["unchanged"], 1)
        self.assertEqual(ExternalFeedEvent.objects.filter(feed=feed).count(), 1)
        self.assertEqual(Disruption.objects.filter(source_key="GDACS:EQ:ARES-TEST-42:1").count(), 1)
        self.assertEqual(RiskAssessmentSnapshot.objects.count(), 1)
        feed.refresh_from_db()
        self.assertEqual(feed.status, "ok")
        self.assertEqual(feed.consecutive_failures, 0)


class AccessControlReliabilityTests(APITestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="operator", password="a-long-test-password-42", email="operator@example.org")
        self.other_user = User.objects.create_user(username="other", password="a-long-test-password-42", email="other@example.org")
        self.client.force_authenticate(user=self.operator)

    def test_outcomes_are_approver_only_for_read_and_write(self):
        disruption = Disruption.objects.create(title="Port closure", severity="high")
        self.assertEqual(self.client.get("/api/risk/outcomes/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post("/api/risk/outcomes/", {"disruption_id": str(disruption.pk), "outcome": "impact"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(RiskOutcome.objects.count(), 0)

        self.operator.groups.add(Group.objects.create(name="ares_approvers"))
        reviewed = self.client.post(
            "/api/risk/outcomes/",
            {"disruption_id": str(disruption.pk), "outcome": "impact", "reviewer_name": "Forged Reviewer", "evidence_notes": "Verified"},
            format="json",
        )
        self.assertEqual(reviewed.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reviewed.data["reviewed_by"], "operator")

    def test_notification_inbox_only_exposes_the_signed_in_recipients(self):
        for email, key in ((self.operator.email, "mine"), (self.other_user.email, "theirs")):
            NotificationDelivery.objects.create(
                idempotency_key=hashlib.sha256(key.encode()).hexdigest(),
                notification_type="risk_alert",
                recipient_email=email,
                subject="Test alert",
                message="Test notification",
            )

        own = self.client.get("/api/notifications/")
        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual([row["recipient_email"] for row in own.data["results"]], [self.operator.email])

        approvers = Group.objects.create(name="ares_approvers")
        self.operator.groups.add(approvers)
        outbox = self.client.get("/api/notifications/")
        self.assertEqual(outbox.status_code, status.HTTP_200_OK)
        self.assertEqual(len(outbox.data["results"]), 2)

    def test_dry_run_action_is_idempotent_and_live_execution_is_approver_gated(self):
        disruption = Disruption.objects.create(title="Route interruption", severity="critical")
        plan = ResponsePlan.objects.create(
            disruption=disruption,
            title="Protect supply",
            owner="Operations",
            status="active",
        )
        action = ResponseAction.objects.create(plan=plan, title="Confirm alternate capacity", owner="Procurement")

        first = self.client.post(
            f"/api/response-actions/{action.pk}/execute/",
            {"dry_run": True},
            format="json",
            HTTP_IDEMPOTENCY_KEY="phase7-dry-run-key",
        )
        replay = self.client.post(
            f"/api/response-actions/{action.pk}/execute/",
            {"dry_run": True},
            format="json",
            HTTP_IDEMPOTENCY_KEY="phase7-dry-run-key",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertFalse(first.data["execution"]["result_summary"]["performed"])
        self.assertTrue(replay.data["idempotent_replay"])
        self.assertEqual(ResponseActionExecution.objects.count(), 1)

        live = self.client.post(
            f"/api/response-actions/{action.pk}/execute/",
            {"dry_run": False},
            format="json",
            HTTP_IDEMPOTENCY_KEY="phase7-live-key",
        )
        self.assertEqual(live.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ResponseActionExecution.objects.count(), 1)


class NotificationReliabilityTests(APITestCase):
    def test_risk_alert_outbox_deduplicates_and_dispatch_records_success(self):
        approver = User.objects.create_user(username="approver", email="approver@example.org")
        approver.groups.add(Group.objects.create(name="ares_approvers"))
        disruption = Disruption.objects.create(title="Critical port closure", severity="critical")

        with patch.dict(os.environ, {
            "ARES_RISK_ALERT_SCORE_THRESHOLD": "0",
            "ARES_RISK_ALERT_COOLDOWN_MINUTES": "60",
            "ARES_NOTIFICATION_OPERATIONS_EMAILS": "ops@example.org",
        }):
            assess_and_record(disruption)
            assess_and_record(disruption)

        alert = RiskAlert.objects.get(disruption=disruption, status="active")
        self.assertEqual(alert.alert_generation_count, 1)
        self.assertEqual(alert.deduplicated_count, 1)
        deliveries = NotificationDelivery.objects.filter(notification_type="risk_alert")
        self.assertEqual(deliveries.count(), 2)
        self.assertSetEqual(set(deliveries.values_list("status", flat=True)), {"pending"})

        with override_settings(
            ARES_EMAIL_DELIVERY_ENABLED=True,
            DEFAULT_FROM_EMAIL="ares@example.org",
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ), patch("supply_chain.notifications.send_mail", return_value=1) as send_mail:
            result = dispatch_notifications(limit=10)

        self.assertEqual(result, {"status": "ok", "sent": 2, "retried": 0, "failed": 0, "attempted": 2})
        self.assertEqual(send_mail.call_count, 2)
        self.assertEqual(deliveries.filter(status="sent").count(), 2)
        self.assertTrue(all(delivery.sent_at for delivery in deliveries))


class SafeApiErrorTests(APITestCase):
    def test_unexpected_exception_details_are_not_returned_to_api_clients(self):
        request = APIRequestFactory().get("/api/suppliers/")
        secret_detail = "connection failed for user private-user with password private-password"
        with patch("config.api_errors.logger.error"):
            response = api_exception_handler(RuntimeError(secret_detail), {"request": request})

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, {"detail": "An unexpected API error occurred."})
        self.assertNotIn("private-password", str(response.data))
