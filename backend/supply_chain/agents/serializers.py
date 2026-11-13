from rest_framework import serializers
from django.conf import settings

from ..models import AgentExecution, AgentExecutionStep
from .contracts import AGENT_IDS, SPECIALIST_AGENT_IDS


class AgentExecutionRequestSerializer(serializers.Serializer):
    agent_id = serializers.ChoiceField(choices=AGENT_IDS)
    question = serializers.CharField(max_length=1200, trim_whitespace=True, allow_blank=False)
    specialists = serializers.ListField(
        child=serializers.ChoiceField(choices=SPECIALIST_AGENT_IDS),
        required=False,
        allow_empty=False,
        max_length=len(SPECIALIST_AGENT_IDS),
    )

    def validate(self, attrs):
        agent_id = attrs["agent_id"]
        if agent_id == "coordinator":
            specialists = attrs.get("specialists", list(SPECIALIST_AGENT_IDS))
            if len(specialists) != len(set(specialists)):
                raise serializers.ValidationError({"specialists": "Each specialist can appear only once."})
            if len(specialists) > settings.ARES_AGENT_MAX_COORDINATOR_SPECIALISTS:
                raise serializers.ValidationError({
                    "specialists": f"This deployment allows at most {settings.ARES_AGENT_MAX_COORDINATOR_SPECIALISTS} specialists per coordination run."
                })
            if len(specialists) > settings.ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS:
                raise serializers.ValidationError({
                    "specialists": "The coordinator's total tool-call budget must allow at least one read for each selected specialist."
                })
            attrs["specialists"] = specialists
        elif "specialists" in attrs:
            raise serializers.ValidationError({"specialists": "Choose specialists only when agent_id is coordinator."})
        return attrs


class AgentExecutionStepReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentExecutionStep
        fields = (
            "id", "sequence", "kind", "agent_id", "status", "input_references", "result",
            "attempt_count", "tool_call_count", "input_tokens", "output_tokens",
            "error_code", "error_message", "started_at", "completed_at", "duration_ms", "created_at",
        )
        read_only_fields = fields


class AgentExecutionReadSerializer(serializers.ModelSerializer):
    steps = AgentExecutionStepReadSerializer(many=True, read_only=True)

    class Meta:
        model = AgentExecution
        fields = (
            "id", "agent_id", "status", "input_references", "result", "provider",
            "model_name", "attempt_count", "tool_call_count", "input_tokens", "steps",
            "output_tokens", "error_code", "error_message", "started_at",
            "completed_at", "duration_ms", "created_at",
        )
        read_only_fields = fields
