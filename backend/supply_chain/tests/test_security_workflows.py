from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase

from supply_chain.models import (
    AuditEvent,
    Disruption,
    Inventory,
    InventoryMovement,
    Material,
    ResponsePlan,
    Supplier,
)


User = get_user_model()


class AuthenticationAndAuthorizationTests(APITestCase):
    def setUp(self):
        self.operator = User.objects.create_user(
            username="operator",
            password="a-long-test-password-42",
            first_name="Casey",
            last_name="Operator",
        )

    def test_supply_chain_api_requires_authentication(self):
        response = self.client.get("/api/overview/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_rotates_token_and_logout_revokes_it(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "operator", "password": "a-long-test-password-42"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["token"])
        self.assertEqual(response.data["user"]["username"], "operator")

        old_token = response.data["token"]
        second_login = self.client.post(
            "/api/auth/login/",
            {"username": "operator", "password": "a-long-test-password-42"},
            format="json",
        )
        self.assertEqual(second_login.status_code, status.HTTP_200_OK)
        self.assertNotEqual(second_login.data["token"], old_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {second_login.data['token']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_api_token_is_revoked(self):
        login = self.client.post(
            "/api/auth/login/",
            {"username": "operator", "password": "a-long-test-password-42"},
            format="json",
        )
        token = login.data["token"]
        from rest_framework.authtoken.models import Token

        Token.objects.filter(key=token).update(created=timezone.now() - timedelta(hours=9))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Token.objects.filter(key=token).exists())

    def test_approval_requires_approver_role_and_uses_authenticated_identity(self):
        disruption = Disruption.objects.create(title="Port closure", severity="high")
        plan = ResponsePlan.objects.create(
            disruption=disruption,
            title="Protect supply",
            owner="Operations",
            status="pending_approval",
        )

        self.client.force_authenticate(user=self.operator)
        denied = self.client.post(
            f"/api/response-plans/{plan.pk}/approve/",
            {"reviewer_name": "Forged Reviewer", "review_notes": "Reviewed"},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        approvers = Group.objects.create(name="ares_approvers")
        self.operator.groups.add(approvers)
        approved = self.client.post(
            f"/api/response-plans/{plan.pk}/approve/",
            {"reviewer_name": "Forged Reviewer", "review_notes": "Capacity confirmed"},
            format="json",
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        self.assertEqual(approved.data["reviewed_by"], "Casey Operator")
        audit = AuditEvent.objects.filter(entity_id=str(plan.pk), action="update").latest("created_at")
        self.assertEqual(audit.actor, "operator")


class OperationalWorkflowTests(APITestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="operator", password="a-long-test-password-42")
        self.client.force_authenticate(user=self.operator)

    def test_response_plan_requires_review_then_tracks_action_and_outcome(self):
        disruption = Disruption.objects.create(title="Route interruption", severity="critical")
        created = self.client.post(
            "/api/response-plans/",
            {
                "disruption": str(disruption.pk),
                "title": "Protect production supply",
                "owner": "Supply chain lead",
                "actions": [{"title": "Confirm alternate capacity", "owner": "Procurement"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        plan_id = created.data["id"]
        action_id = created.data["actions"][0]["id"]

        cannot_start = self.client.post(f"/api/response-plans/{plan_id}/start/", {}, format="json")
        self.assertEqual(cannot_start.status_code, status.HTTP_400_BAD_REQUEST)

        submitted = self.client.post(f"/api/response-plans/{plan_id}/submit/", {}, format="json")
        self.assertEqual(submitted.status_code, status.HTTP_200_OK)
        approvers = Group.objects.create(name="ares_approvers")
        self.operator.groups.add(approvers)
        approved = self.client.post(
            f"/api/response-plans/{plan_id}/approve/",
            {"review_notes": "Alternate supplier confirmed"},
            format="json",
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        self.assertEqual(approved.data["reviewed_by"], "operator")
        self.assertEqual(self.client.post(f"/api/response-plans/{plan_id}/start/", {}, format="json").status_code, status.HTTP_200_OK)

        action_update = self.client.patch(
            f"/api/response-actions/{action_id}/",
            {"status": "completed", "outcome": "Capacity secured"},
            format="json",
        )
        self.assertEqual(action_update.status_code, status.HTTP_200_OK)
        completed = self.client.post(
            f"/api/response-plans/{plan_id}/complete/",
            {"outcome": "Production remained supplied"},
            format="json",
        )
        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        self.assertEqual(completed.data["status"], "completed")
        self.assertGreaterEqual(AuditEvent.objects.filter(entity_id=str(plan_id)).count(), 4)

    def test_invalid_inventory_issue_is_rejected_without_changing_balance(self):
        supplier = Supplier.objects.create(name="Northstar Components", code="NORTHSTAR")
        material = Material.objects.create(sku="NS-01", name="Control module", preferred_supplier=supplier)
        inventory = Inventory.objects.create(material=material, location="Plant 1", quantity=10, reorder_point=2)

        response = self.client.post(
            "/api/inventory-movements/",
            {"inventory": str(inventory.pk), "movement_type": "issue", "quantity_delta": "-12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        inventory.refresh_from_db()
        self.assertEqual(str(inventory.quantity), "10.00")
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_risk_assessment_validation_returns_field_errors(self):
        response = self.client.post("/api/risk/assess/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)
