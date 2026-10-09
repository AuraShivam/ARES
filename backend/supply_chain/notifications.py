"""Database-backed email outbox for approval and risk notifications."""

import hashlib
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import NotificationDelivery


MAX_DELIVERY_ATTEMPTS = 5
SENDING_LEASE_MINUTES = 10


def _operations_recipients():
    values = os.getenv("ARES_NOTIFICATION_OPERATIONS_EMAILS", "").split(",")
    recipients = set()
    for value in values:
        email = value.strip().casefold()
        if not email:
            continue
        try:
            validate_email(email)
        except Exception:
            continue
        recipients.add(email)
    return recipients


def _is_valid_email(email):
    if not email:
        return False
    try:
        validate_email(email)
    except Exception:
        return False
    return True


def _approver_recipients():
    User = get_user_model()
    return {
        email.strip().casefold()
        for email in User.objects.filter(is_active=True)
        .filter(Q(is_staff=True) | Q(groups__name="ares_approvers"))
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
        if _is_valid_email(email.strip())
    }


def _plan_recipients(plan, *, approvers=False):
    recipients = _operations_recipients()
    if approvers:
        recipients |= _approver_recipients()
    if plan.created_by_id and plan.created_by.is_active and plan.created_by.email:
        recipients.add(plan.created_by.email.strip().casefold())
    return recipients


def _enqueue(event_key, notification_type, recipients, subject, message):
    """Create one idempotent delivery row per recipient inside the caller's transaction."""
    normalized = sorted({email.strip().casefold() for email in recipients if email.strip()})
    targets = normalized or [""]
    for email in targets:
        digest = hashlib.sha256(f"{event_key}:{email}".encode("utf-8")).hexdigest()
        NotificationDelivery.objects.get_or_create(
            idempotency_key=digest,
            defaults={
                "notification_type": notification_type,
                "recipient_email": email,
                "subject": subject[:240],
                "message": message,
                "status": "pending" if email else "unroutable",
                "error_code": "no_recipient_configured" if not email else "",
            },
        )


def queue_plan_notification(plan, event_type, description):
    recipients = _plan_recipients(plan, approvers=event_type == "plan_submitted")
    event_key = f"plan:{plan.pk}:{event_type}:{plan.updated_at.isoformat()}"
    subject = f"ARES response plan {event_type.replace('_', ' ')}: {plan.title}"
    message = (
        f"ARES response plan update\n\n"
        f"Plan: {plan.title}\n"
        f"Disruption: {plan.disruption.title}\n"
        f"Status: {plan.get_status_display()}\n"
        f"Update: {description}\n"
        f"Plan ID: {plan.pk}\n"
    )
    _enqueue(event_key, event_type, recipients, subject, message)


def queue_action_notification(action):
    plan = action.plan
    recipients = _plan_recipients(plan)
    owner_email = action.owner.strip().casefold()
    if _is_valid_email(owner_email):
        recipients.add(owner_email)
    event_key = f"action:{action.pk}:{action.updated_at.isoformat()}"
    subject = f"ARES response task updated: {action.title}"
    message = (
        f"ARES response task update\n\n"
        f"Task: {action.title}\n"
        f"Plan: {plan.title}\n"
        f"Disruption: {plan.disruption.title}\n"
        f"Owner: {action.owner}\n"
        f"Status: {action.get_status_display()}\n"
        f"Action ID: {action.pk}\n"
    )
    _enqueue(event_key, "action_updated", recipients, subject, message)


def queue_risk_alert_notification(alert, generation=None, *, cleared=False):
    recipients = _approver_recipients() | _operations_recipients()
    event_type = "risk_alert_cleared" if cleared else "risk_alert"
    generation_key = generation or 1
    event_key = f"risk-alert:{alert.pk}:{event_type}:{generation_key}"
    state = "cleared" if cleared else "active"
    subject = f"ARES risk alert {state}: {alert.disruption.title}"
    message = (
        f"ARES advisory risk alert {state}\n\n"
        f"Disruption: {alert.disruption.title}\n"
        f"Risk score: {alert.risk_score}/100 ({alert.risk_band})\n"
        f"Alert threshold: {alert.threshold_score}/100\n"
        f"Alert ID: {alert.pk}\n"
        f"Disruption ID: {alert.disruption_id}\n"
        "Review the linked disruption and approve any operational response before action.\n"
    )
    _enqueue(event_key, event_type, recipients, subject, message)


def _claim_next_delivery(now):
    stale_before = now - timedelta(minutes=SENDING_LEASE_MINUTES)
    with transaction.atomic():
        delivery = (
            NotificationDelivery.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status__in=["pending", "retry"], attempt_count__lt=MAX_DELIVERY_ATTEMPTS)
                & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                | Q(status="sending", last_attempt_at__lte=stale_before, attempt_count__lt=MAX_DELIVERY_ATTEMPTS)
            )
            .order_by("created_at")
            .first()
        )
        if delivery is None:
            return None
        delivery.status = "sending"
        delivery.attempt_count += 1
        delivery.last_attempt_at = now
        delivery.next_attempt_at = None
        delivery.error_code = ""
        delivery.save(update_fields=[
            "status", "attempt_count", "last_attempt_at", "next_attempt_at", "error_code", "updated_at",
        ])
        return delivery


def dispatch_notifications(limit=100):
    """Deliver due emails; records remain queued unless delivery is explicitly enabled."""
    if not settings.ARES_EMAIL_DELIVERY_ENABLED:
        return {"status": "disabled", "sent": 0, "retried": 0, "failed": 0, "attempted": 0}
    if not (settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER):
        return {"status": "configuration_error", "detail": "notification sender is not configured", "sent": 0, "retried": 0, "failed": 0, "attempted": 0}
    if settings.EMAIL_BACKEND.endswith("smtp.EmailBackend") and not settings.EMAIL_HOST:
        return {"status": "configuration_error", "detail": "SMTP host is not configured", "sent": 0, "retried": 0, "failed": 0, "attempted": 0}
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        return {"status": "configuration_error", "detail": "choose either SMTP TLS or SSL", "sent": 0, "retried": 0, "failed": 0, "attempted": 0}

    now = timezone.now()
    NotificationDelivery.objects.filter(
        status="sending",
        last_attempt_at__lte=now - timedelta(minutes=SENDING_LEASE_MINUTES),
        attempt_count__gte=MAX_DELIVERY_ATTEMPTS,
    ).update(
        status="failed",
        error_code="worker_lease_expired",
        next_attempt_at=None,
        updated_at=now,
    )

    counts = {"status": "ok", "sent": 0, "retried": 0, "failed": 0, "attempted": 0}
    for _index in range(max(1, min(int(limit), 1000))):
        delivery = _claim_next_delivery(timezone.now())
        if delivery is None:
            break
        counts["attempted"] += 1
        try:
            sender = settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
            if not sender:
                raise ValueError("notification_sender_not_configured")
            sent = send_mail(
                delivery.subject,
                delivery.message,
                sender,
                [delivery.recipient_email],
                fail_silently=False,
            )
            if sent != 1:
                raise RuntimeError("email_backend_did_not_accept_message")
        except Exception as exc:
            now = timezone.now()
            exhausted = delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS
            delivery.status = "failed" if exhausted else "retry"
            delivery.error_code = type(exc).__name__[:80] or "delivery_error"
            delivery.next_attempt_at = None if exhausted else now + timedelta(minutes=min(2 ** delivery.attempt_count, 60))
            delivery.save(update_fields=["status", "error_code", "next_attempt_at", "updated_at"])
            counts["failed" if exhausted else "retried"] += 1
            continue

        delivery.status = "sent"
        delivery.sent_at = timezone.now()
        delivery.error_code = ""
        delivery.save(update_fields=["status", "sent_at", "error_code", "updated_at"])
        counts["sent"] += 1
    return counts
