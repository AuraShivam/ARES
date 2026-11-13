import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from supply_chain.agents.providers import provider_readiness
from supply_chain.agents.tools import AgentToolFailure, execute_read_tool, list_tools
from supply_chain.models import AgentExecution, Supplier


class FakeResponsesProvider:
    def __init__(self):
        self.calls = 0
        self.tool_names_per_call = []

    def create_response(self, input_items, tool_definitions, output_schema, timeout_seconds, *, instructions):
        self.calls += 1
        self.tool_names_per_call.append({tool["name"] for tool in tool_definitions})
        if self.calls == 1:
            return {
                "status": "completed",
                "output": [{
                    "type": "function_call",
                    "name": "get_data_readiness",
                    "call_id": "readiness-call-1",
                    "arguments": "{}",
                }],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }

        tool_result = next(
            json.loads(item["output"])
            for item in input_items
            if item.get("type") == "function_call_output"
        )
        reference = tool_result["evidence_references"][0]
        result = {
            "findings": [{
                "code": "readiness_observed",
                "title": "Readiness data inspected",
                "summary": "The ARES readiness report was inspected.",
                "severity": "info",
                "evidence_references": [reference],
            }],
            "evidence_references": [reference],
            "recommendations": [{
                "action": "review_data",
                "title": "Review source coverage",
                "summary": "A planner can review the recorded readiness information.",
                "evidence_references": [reference],
            }],
            "assumptions": [],
            "confidence": 0.75,
            "uncertainty": "This is a runtime integration fixture, not a production assessment.",
        }
        return {
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(result)}],
            }],
            "usage": {"input_tokens": 18, "output_tokens": 20},
        }


class AgentRuntimeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="agent-user", password="not-used")
        self.client.force_authenticate(user=self.user)

    def test_status_is_explicit_when_provider_is_disabled_and_never_exposes_key(self):
        with override_settings(
            ARES_AGENT_PROVIDER="disabled",
            ARES_AGENT_API_KEY="private-test-key",
            ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=False,
        ):
            response = self.client.get("/api/ai/status/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["runtime"]["status"], "unavailable")
        self.assertFalse(response.data["runtime"]["external_processing_enabled"])
        self.assertEqual(response.data["execution_limits"]["requests_per_user_per_hour"], 5)
        self.assertEqual(response.data["multi_agent_orchestration"], "sequential_specialist_pipeline")
        self.assertNotIn("private-test-key", json.dumps(response.data))
        self.assertFalse(response.data["provider_reachability_checked"])

    def test_data_readiness_reflects_runtime_unavailability(self):
        response = self.client.get("/api/ai/data-readiness/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["capabilities"]["agent_runtime"]["status"], "unavailable")

    def test_registry_advertises_only_read_only_tools(self):
        self.assertTrue(list_tools())
        self.assertEqual({tool["access"] for tool in list_tools()}, {"read_only"})
        with self.assertRaises(AgentToolFailure) as error:
            execute_read_tool("create_purchase_order", {}, self.user)
        self.assertEqual(error.exception.code, "tool_not_allowed")

    def test_tool_reads_supplier_without_modifying_it(self):
        supplier = Supplier.objects.create(name="Northwind", code="SUP-NW")

        result = execute_read_tool("get_supplier", {"reference": supplier.code}, self.user)

        supplier.refresh_from_db()
        self.assertEqual(result["data"]["name"], "Northwind")
        self.assertEqual(result["evidence_references"][0]["reference_id"], str(supplier.pk))
        self.assertEqual(Supplier.objects.count(), 1)

    def test_role_cannot_invoke_a_tool_outside_its_allowlist(self):
        with self.assertRaises(AgentToolFailure) as error:
            execute_read_tool("get_purchase_order", {"reference": "PO-1"}, self.user, {"get_inventory"})
        self.assertEqual(error.exception.code, "tool_not_allowed")

    def test_execution_is_recorded_as_unavailable_when_provider_is_not_configured(self):
        response = self.client.post(
            "/api/ai/executions/",
            {"agent_id": "coordinator", "question": "Summarize current supply-chain signals."},
            format="json",
            HTTP_IDEMPOTENCY_KEY="agent-disabled-001",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        execution = AgentExecution.objects.get(requested_by=self.user)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.error_code, "provider_disabled")
        self.assertEqual(len(execution.idempotency_key), 64)

    @override_settings(
        ARES_AGENT_PROVIDER="openai_responses",
        ARES_AGENT_MODEL="test-model",
        ARES_AGENT_API_KEY="private-test-key",
        ARES_AGENT_API_BASE_URL="https://provider.example.test/v1",
        ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ARES_AGENT_TIMEOUT_SECONDS=10,
        ARES_AGENT_MAX_TOOL_CALLS=4,
        ARES_AGENT_MAX_OUTPUT_TOKENS=1200,
    )
    def test_configured_runtime_calls_read_only_tool_and_validates_evidence(self):
        fake = FakeResponsesProvider()
        with patch("supply_chain.agents.runtime.get_provider", return_value=fake):
            response = self.client.post(
                "/api/ai/executions/",
                {"agent_id": "inventory_intelligence", "question": "Check whether ARES demand forecasts have enough recorded history."},
                format="json",
                HTTP_IDEMPOTENCY_KEY="agent-ready-001",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        execution_data = response.data["execution"]
        self.assertEqual(execution_data["status"], "succeeded")
        self.assertEqual(execution_data["tool_call_count"], 1)
        self.assertEqual(execution_data["attempt_count"], 2)
        self.assertEqual(execution_data["input_tokens"], 30)
        self.assertEqual(execution_data["result"]["recommendations"][0]["requires_human_approval"], True)
        self.assertIn("get_inventory", fake.tool_names_per_call[0])
        self.assertNotIn("get_disruption", fake.tool_names_per_call[0])
        self.assertNotIn("private-test-key", json.dumps(response.data))
        self.assertEqual(provider_readiness()["status"], "configured")

    @override_settings(
        ARES_AGENT_PROVIDER="openai_responses",
        ARES_AGENT_MODEL="test-model",
        ARES_AGENT_API_KEY="private-test-key",
        ARES_AGENT_API_BASE_URL="https://provider.example.test/v1",
        ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ARES_AGENT_TIMEOUT_SECONDS=10,
        ARES_AGENT_MAX_TOOL_CALLS=4,
        ARES_AGENT_MAX_OUTPUT_TOKENS=1200,
    )
    def test_idempotent_replay_does_not_call_provider_twice(self):
        fake = FakeResponsesProvider()
        body = {"agent_id": "coordinator", "question": "Summarize recorded ARES data readiness."}
        with patch("supply_chain.agents.runtime.get_provider", return_value=fake):
            first = self.client.post("/api/ai/executions/", body, format="json", HTTP_IDEMPOTENCY_KEY="agent-replay-001")
            replay = self.client.post("/api/ai/executions/", body, format="json", HTTP_IDEMPOTENCY_KEY="agent-replay-001")
            conflict = self.client.post(
                "/api/ai/executions/",
                {"agent_id": "coordinator", "question": "Different request."},
                format="json",
                HTTP_IDEMPOTENCY_KEY="agent-replay-001",
            )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.status_code, status.HTTP_200_OK)
        self.assertTrue(replay.data["idempotent_replay"])
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(fake.calls, 2)


class ProviderReadinessTests(TestCase):
    def test_remote_http_endpoint_is_rejected(self):
        with override_settings(
            ARES_AGENT_PROVIDER="openai_responses",
            ARES_AGENT_MODEL="test-model",
            ARES_AGENT_API_KEY="test-key",
            ARES_AGENT_API_BASE_URL="http://provider.example.test/v1",
            ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ):
            readiness = provider_readiness()

        self.assertEqual(readiness["status"], "unavailable")
        self.assertEqual(readiness["code"], "invalid_provider_endpoint")
