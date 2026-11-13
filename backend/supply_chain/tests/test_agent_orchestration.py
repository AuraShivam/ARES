import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from supply_chain.agents.contracts import SPECIALIST_AGENT_IDS
from supply_chain.agents.providers import ProviderFailure
from supply_chain.agents.serializers import AgentExecutionRequestSerializer
from supply_chain.models import AgentExecution, AgentExecutionStep


class FakeCoordinatedResponsesProvider:
    def __init__(self):
        self.calls = []

    def create_response(self, input_items, tool_definitions, output_schema, timeout_seconds, *, instructions):
        self.calls.append({
            "input_items": input_items,
            "tool_names": {tool["name"] for tool in tool_definitions},
            "instructions": instructions,
        })
        if tool_definitions:
            tool_outputs = [item for item in input_items if item.get("type") == "function_call_output"]
            if not tool_outputs:
                return {
                    "status": "completed",
                    "output": [{
                        "type": "function_call",
                        "name": "get_data_readiness",
                        "call_id": f"readiness-{len(self.calls)}",
                        "arguments": "{}",
                    }],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                }
            tool_result = json.loads(tool_outputs[-1]["output"])
            reference = tool_result["evidence_references"][0]
            return self._message(self._result("Specialist inspected ARES data.", [reference]), 10, 8)

        context = json.loads(input_items[0]["content"][0]["text"])
        references = []
        for report in context["specialist_reports"]:
            references.extend(report["result"]["input_references"])
        unique_references = list({json.dumps(item, sort_keys=True): item for item in references}.values())
        return self._message(self._result("Coordinator combined the specialist evidence.", unique_references), 15, 10)

    @staticmethod
    def _result(summary, references):
        cited = references[:1]
        return {
            "findings": [{
                "code": "coordination_fixture",
                "title": "Evidence inspected",
                "summary": summary,
                "severity": "info",
                "evidence_references": cited,
            }],
            "evidence_references": references,
            "recommendations": [],
            "assumptions": [],
            "confidence": 0.8,
            "uncertainty": "Fixture output for orchestration tests.",
        }

    @staticmethod
    def _message(result, input_tokens, output_tokens):
        return {
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(result)}],
            }],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }


class FailingSpecialistProvider:
    def create_response(self, *args, **kwargs):
        raise ProviderFailure("provider_auth_failed", "The configured provider rejected authentication.")


class AgentOrchestrationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="coordinator-user", password="not-used")
        self.client.force_authenticate(user=self.user)

    @override_settings(
        ARES_AGENT_PROVIDER="openai_responses",
        ARES_AGENT_MODEL="test-model",
        ARES_AGENT_API_KEY="private-test-key",
        ARES_AGENT_API_BASE_URL="https://provider.example.test/v1",
        ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ARES_AGENT_TIMEOUT_SECONDS=30,
        ARES_AGENT_MAX_TOOL_CALLS=4,
        ARES_AGENT_MAX_OUTPUT_TOKENS=1200,
        ARES_AGENT_MAX_COORDINATOR_SPECIALISTS=5,
        ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS=12,
    )
    def test_coordinator_runs_selected_specialists_and_synthesizes_verified_evidence(self):
        fake = FakeCoordinatedResponsesProvider()
        with patch("supply_chain.agents.runtime.get_provider", return_value=fake):
            response = self.client.post(
                "/api/ai/executions/",
                {
                    "agent_id": "coordinator",
                    "question": "Summarize inventory and supplier exposure.",
                    "specialists": ["inventory_intelligence", "supplier_intelligence"],
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY="coordinator-run-001",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        execution_data = response.data["execution"]
        self.assertEqual(execution_data["status"], "succeeded")
        self.assertEqual(execution_data["tool_call_count"], 2)
        self.assertEqual(execution_data["attempt_count"], 5)
        self.assertEqual([step["agent_id"] for step in execution_data["steps"]], [
            "inventory_intelligence", "supplier_intelligence", "coordinator",
        ])
        self.assertEqual([step["kind"] for step in execution_data["steps"]], [
            "specialist", "specialist", "coordination",
        ])
        self.assertTrue(all(step["status"] == "succeeded" for step in execution_data["steps"]))
        self.assertEqual(execution_data["result"]["findings"][0]["summary"], "Coordinator combined the specialist evidence.")
        self.assertGreaterEqual(len(execution_data["input_references"]), 1)
        self.assertEqual(fake.calls[-1]["tool_names"], set())
        self.assertIn("supply-chain analysis coordinator", fake.calls[-1]["instructions"])
        self.assertEqual(AgentExecutionStep.objects.filter(execution__requested_by=self.user).count(), 3)

    @override_settings(ARES_AGENT_MAX_COORDINATOR_SPECIALISTS=2)
    def test_coordinator_defaults_to_all_roles_only_when_the_configured_limit_allows(self):
        serializer = AgentExecutionRequestSerializer(data={
            "agent_id": "coordinator",
            "question": "Summarize current supply-chain risk.",
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("specialists", serializer.errors)

        limited = AgentExecutionRequestSerializer(data={
            "agent_id": "coordinator",
            "question": "Summarize current supply-chain risk.",
            "specialists": ["risk_intelligence", "inventory_intelligence"],
        })
        self.assertTrue(limited.is_valid(), limited.errors)

    def test_specialist_selection_is_unique_and_coordinator_only(self):
        duplicate = AgentExecutionRequestSerializer(data={
            "agent_id": "coordinator",
            "question": "Review suppliers.",
            "specialists": ["supplier_intelligence", "supplier_intelligence"],
        })
        self.assertFalse(duplicate.is_valid())

        on_specialist = AgentExecutionRequestSerializer(data={
            "agent_id": "risk_intelligence",
            "question": "Review this disruption.",
            "specialists": ["supplier_intelligence"],
        })
        self.assertFalse(on_specialist.is_valid())

        self.assertEqual(len(SPECIALIST_AGENT_IDS), 5)

    @override_settings(
        ARES_AGENT_PROVIDER="openai_responses",
        ARES_AGENT_MODEL="test-model",
        ARES_AGENT_API_KEY="private-test-key",
        ARES_AGENT_API_BASE_URL="https://provider.example.test/v1",
        ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ARES_AGENT_TIMEOUT_SECONDS=30,
        ARES_AGENT_MAX_TOOL_CALLS=4,
        ARES_AGENT_MAX_OUTPUT_TOKENS=1200,
        ARES_AGENT_MAX_COORDINATOR_SPECIALISTS=5,
        ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS=12,
    )
    def test_idempotency_hash_includes_specialist_selection(self):
        fake = FakeCoordinatedResponsesProvider()
        with patch("supply_chain.agents.runtime.get_provider", return_value=fake):
            first = self.client.post(
                "/api/ai/executions/",
                {"agent_id": "coordinator", "question": "Review supplier exposure.", "specialists": ["supplier_intelligence"]},
                format="json",
                HTTP_IDEMPOTENCY_KEY="coordinator-key-001",
            )
            conflict = self.client.post(
                "/api/ai/executions/",
                {"agent_id": "coordinator", "question": "Review supplier exposure.", "specialists": ["risk_intelligence"]},
                format="json",
                HTTP_IDEMPOTENCY_KEY="coordinator-key-001",
            )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(AgentExecution.objects.filter(requested_by=self.user).count(), 1)

    @override_settings(
        ARES_AGENT_PROVIDER="openai_responses",
        ARES_AGENT_MODEL="test-model",
        ARES_AGENT_API_KEY="private-test-key",
        ARES_AGENT_API_BASE_URL="https://provider.example.test/v1",
        ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=True,
        ARES_AGENT_TIMEOUT_SECONDS=30,
        ARES_AGENT_MAX_TOOL_CALLS=4,
        ARES_AGENT_MAX_OUTPUT_TOKENS=1200,
        ARES_AGENT_MAX_COORDINATOR_SPECIALISTS=5,
        ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS=12,
    )
    def test_failed_specialist_stage_is_persisted_on_parent_execution(self):
        with patch("supply_chain.agents.runtime.get_provider", return_value=FailingSpecialistProvider()):
            response = self.client.post(
                "/api/ai/executions/",
                {
                    "agent_id": "coordinator",
                    "question": "Review supplier delivery exposure.",
                    "specialists": ["supplier_intelligence"],
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY="coordinator-fail-001",
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        execution = AgentExecution.objects.get(requested_by=self.user)
        step = AgentExecutionStep.objects.get(execution=execution)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(step.agent_id, "supplier_intelligence")
        self.assertEqual(step.status, "failed")
        self.assertEqual(step.error_code, "provider_auth_failed")
        self.assertEqual(execution.attempt_count, 1)
