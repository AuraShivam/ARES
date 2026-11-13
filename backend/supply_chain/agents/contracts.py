"""Versioned, provider-neutral contracts for bounded ARES agent executions.

These serializers validate messages; they do not call a provider or imply that
one is configured.
"""

from rest_framework import serializers


AGENT_IDS = (
    "risk_intelligence",
    "supplier_intelligence",
    "inventory_intelligence",
    "logistics_intelligence",
    "procurement_intelligence",
    "coordinator",
)

SPECIALIST_AGENT_IDS = (
    "risk_intelligence",
    "supplier_intelligence",
    "inventory_intelligence",
    "logistics_intelligence",
    "procurement_intelligence",
)

EXECUTION_STATUSES = ("pending", "running", "succeeded", "partial", "failed", "cancelled")
FINDING_SEVERITIES = ("info", "low", "medium", "high", "critical", "unknown")


class ReferenceSerializer(serializers.Serializer):
    """Pointer to an ARES record, source event, or explicitly named data metric."""

    reference_type = serializers.CharField(max_length=80)
    reference_id = serializers.CharField(max_length=160)
    source_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    observed_at = serializers.DateTimeField(required=False, allow_null=True)


class FindingSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)
    title = serializers.CharField(max_length=180)
    summary = serializers.CharField(max_length=2000)
    severity = serializers.ChoiceField(choices=FINDING_SEVERITIES, default="unknown")
    evidence_references = ReferenceSerializer(many=True, allow_empty=False)


class RecommendationSerializer(serializers.Serializer):
    action = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=180)
    summary = serializers.CharField(max_length=2000)
    evidence_references = ReferenceSerializer(many=True, allow_empty=False)
    requires_human_approval = serializers.BooleanField(default=True)


class AgentErrorSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)
    message = serializers.CharField(max_length=500)
    retryable = serializers.BooleanField(default=False)


class ModelReferenceSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=80, required=False, allow_blank=True)
    model = serializers.CharField(max_length=120, required=False, allow_blank=True)
    version = serializers.CharField(max_length=120, required=False, allow_blank=True)


class AgentExecutionResultSerializer(serializers.Serializer):
    """Common structured output shared by specialist agents and the coordinator."""

    contract_version = serializers.CharField(max_length=20, default="1.0")
    agent_id = serializers.ChoiceField(choices=AGENT_IDS)
    execution_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=EXECUTION_STATUSES)
    input_references = ReferenceSerializer(many=True, allow_empty=True)
    findings = FindingSerializer(many=True, allow_empty=True)
    evidence_references = ReferenceSerializer(many=True, allow_empty=True)
    recommendations = RecommendationSerializer(many=True, allow_empty=True)
    assumptions = serializers.ListField(child=serializers.CharField(max_length=500), allow_empty=True)
    confidence = serializers.FloatField(min_value=0, max_value=1, required=False, allow_null=True)
    uncertainty = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    errors = AgentErrorSerializer(many=True, allow_empty=True)
    executed_at = serializers.DateTimeField()
    model = ModelReferenceSerializer(required=False)

    def validate(self, attrs):
        if attrs.get("confidence") is None and not attrs.get("uncertainty", "").strip():
            raise serializers.ValidationError({
                "uncertainty": "Provide uncertainty when confidence is unknown."
            })
        if attrs["status"] == "succeeded" and attrs["errors"]:
            raise serializers.ValidationError({
                "errors": "A succeeded execution cannot contain execution errors; use partial or failed."
            })
        return attrs
