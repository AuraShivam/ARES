from datetime import datetime, timezone as dt_timezone
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from supply_chain.agents.contracts import AgentExecutionResultSerializer


class AgentDataReadinessApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = get_user_model().objects.create_user(username="readiness-viewer", password="not-used")
        self.client.force_authenticate(user=user)

    def test_readiness_endpoint_is_read_only_and_reports_data_boundaries(self):
        response = self.client.get("/api/ai/data-readiness/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["as_of_date"], timezone.localdate().isoformat())
        self.assertIn("shipment_delay_prediction", response.data["capabilities"])
        self.assertEqual(response.data["capabilities"]["agent_runtime"]["status"], "not_implemented")
        self.assertIn("data_model_gaps", response.data)

    def test_readiness_endpoint_rejects_writes(self):
        response = self.client.post("/api/ai/data-readiness/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class AgentExecutionContractTests(TestCase):
    def _result(self):
        return {
            "agent_id": "inventory_intelligence",
            "execution_id": str(uuid4()),
            "status": "succeeded",
            "input_references": [],
            "findings": [{
                "code": "stock_record",
                "title": "Stock level recorded",
                "summary": "The inventory balance is available.",
                "severity": "info",
                "evidence_references": [{
                    "reference_type": "inventory",
                    "reference_id": "inventory-1",
                }],
            }],
            "evidence_references": [],
            "recommendations": [],
            "assumptions": [],
            "confidence": 0.9,
            "errors": [],
            "executed_at": datetime.now(dt_timezone.utc).isoformat(),
        }

    def test_valid_result_is_normalized_by_shared_contract(self):
        serializer = AgentExecutionResultSerializer(data=self._result())

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["contract_version"], "1.0")

    def test_findings_require_evidence_references(self):
        payload = self._result()
        payload["findings"][0]["evidence_references"] = []
        serializer = AgentExecutionResultSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("findings", serializer.errors)

    def test_unknown_confidence_requires_uncertainty_explanation(self):
        payload = self._result()
        payload["confidence"] = None
        serializer = AgentExecutionResultSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("uncertainty", serializer.errors)

    def test_success_result_cannot_contain_execution_errors(self):
        payload = self._result()
        payload["errors"] = [{"code": "provider_error", "message": "Provider failed."}]
        serializer = AgentExecutionResultSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("errors", serializer.errors)
