from rest_framework import serializers

from ..models import AgentExecution
from .contracts import AGENT_IDS


class AgentExecutionRequestSerializer(serializers.Serializer):
    agent_id = serializers.ChoiceField(choices=AGENT_IDS)
    question = serializers.CharField(max_length=1200, trim_whitespace=True, allow_blank=False)


class AgentExecutionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentExecution
        fields = (
            "id", "agent_id", "status", "input_references", "result", "provider",
            "model_name", "attempt_count", "tool_call_count", "input_tokens",
            "output_tokens", "error_code", "error_message", "started_at",
            "completed_at", "duration_ms", "created_at",
        )
        read_only_fields = fields
