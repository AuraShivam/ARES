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
    workflow_disruption_title = serializers.CharField(source="workflow_disruption.title", read_only=True, default=None)
    workflow_assessment_risk_score = serializers.IntegerField(source="workflow_assessment_snapshot.risk_score", read_only=True, default=None)
    handoff_plans = serializers.SerializerMethodField()

    class Meta:
        model = AgentExecution
        fields = (
            "id", "agent_id", "status", "input_references", "result", "provider",
            "model_name", "attempt_count", "tool_call_count", "input_tokens", "steps",
            "output_tokens", "error_code", "error_message", "started_at",
            "completed_at", "duration_ms", "created_at", "workflow_disruption",
            "workflow_assessment_snapshot", "workflow_disruption_title",
            "workflow_assessment_risk_score", "handoff_plans",
        )
        read_only_fields = fields

    def get_handoff_plans(self, obj):
        return [{
            "id": str(plan.pk), "title": plan.title, "status": plan.status,
            "source_recommendation_index": plan.source_recommendation_index,
        } for plan in obj.response_plans.all()]


class DisruptionWorkflowRequestSerializer(serializers.Serializer):
    disruption_id = serializers.UUIDField()
    assessment_snapshot_id = serializers.UUIDField()
    specialists = serializers.ListField(
        child=serializers.ChoiceField(choices=SPECIALIST_AGENT_IDS),
        required=False, allow_empty=False, max_length=len(SPECIALIST_AGENT_IDS),
    )

    def validate(self, attrs):
        specialists = attrs.get("specialists", list(SPECIALIST_AGENT_IDS))
        if len(specialists) != len(set(specialists)):
            raise serializers.ValidationError({"specialists": "Each specialist can appear only once."})
        if "risk_intelligence" not in specialists:
            raise serializers.ValidationError({
                "specialists": "The risk-intelligence specialist is required to inspect the selected assessment snapshot."
            })
        if len(specialists) > settings.ARES_AGENT_MAX_COORDINATOR_SPECIALISTS:
            raise serializers.ValidationError({
                "specialists": f"This deployment allows at most {settings.ARES_AGENT_MAX_COORDINATOR_SPECIALISTS} specialists per workflow."
            })
        if len(specialists) > settings.ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS:
            raise serializers.ValidationError({
                "specialists": "The coordinator tool-call budget must allow at least one read for each selected specialist."
            })
        attrs["specialists"] = specialists
        return attrs


class DisruptionWorkflowHandoffSerializer(serializers.Serializer):
    recommendation_index = serializers.IntegerField(min_value=0, max_value=32767)
    plan_title = serializers.CharField(max_length=180, trim_whitespace=True, allow_blank=False)
    plan_owner = serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=False)
    action_title = serializers.CharField(max_length=180, trim_whitespace=True, allow_blank=False)
    action_owner = serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=False)
    action_description = serializers.CharField(max_length=5000, required=False, allow_blank=True, trim_whitespace=True)
    due_date = serializers.DateField(required=False, allow_null=True)
