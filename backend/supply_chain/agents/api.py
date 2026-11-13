"""Authenticated status, execution, and read-only tool endpoints."""

import re

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from ..agentic_data_readiness import build_agent_data_readiness
from ..models import (
    AgentExecution, AuditEvent, Disruption, ResponseAction, ResponsePlan,
    RiskAssessmentSnapshot,
)
from ..serializers import ResponsePlanSerializer
from .contracts import SPECIALIST_AGENT_IDS
from .providers import provider_readiness
from .runtime import AgentExecutionFailure, execute_agent, governance_metadata
from .serializers import (
    AgentExecutionReadSerializer, AgentExecutionRequestSerializer,
    DisruptionWorkflowHandoffSerializer, DisruptionWorkflowRequestSerializer,
)
from .tools import list_tools


class AgentExecutionThrottle(UserRateThrottle):
    scope = "ares_agent_execution"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def data_readiness(request):
    """Report current operational-data coverage for planned AI capabilities."""
    return Response(build_agent_data_readiness())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_status(request):
    configuration = provider_readiness()
    return Response({
        "runtime": configuration,
        "supported_agent_roles": ["risk_intelligence", "supplier_intelligence", "inventory_intelligence", "logistics_intelligence", "procurement_intelligence", "coordinator"],
        "supported_specialists": list(SPECIALIST_AGENT_IDS),
        "configured_tool_count": len(list_tools()),
        "tool_access": "read_only",
        "external_processing_notice": "When explicitly enabled and configured, the question and selected read-only ARES tool results are sent to the external model provider.",
        "execution_mode": "synchronous_bounded_agent_workflow",
        "execution_limits": {
            "requests_per_user_per_hour": 5,
            "timeout_seconds": settings.ARES_AGENT_TIMEOUT_SECONDS,
            "max_tool_calls": settings.ARES_AGENT_MAX_TOOL_CALLS,
            "max_output_tokens": settings.ARES_AGENT_MAX_OUTPUT_TOKENS,
            "max_question_characters": 1200,
            "max_coordinator_specialists": settings.ARES_AGENT_MAX_COORDINATOR_SPECIALISTS,
            "max_coordinator_tool_calls": settings.ARES_AGENT_MAX_COORDINATOR_TOOL_CALLS,
        },
        "multi_agent_orchestration": "sequential_specialist_pipeline",
        "governance": governance_metadata(),
        "provider_reachability_checked": False,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_tools(request):
    return Response({"tools": list_tools()})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AgentExecutionThrottle])
def agent_executions(request):
    if request.method == "GET":
        executions = AgentExecution.objects.filter(requested_by=request.user).select_related(
            "workflow_disruption", "workflow_assessment_snapshot",
        ).prefetch_related("steps", "response_plans").order_by("-created_at")[:50]
        return Response({"executions": AgentExecutionReadSerializer(executions, many=True).data})

    serializer = AgentExecutionRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise ValidationError({"Idempotency-Key": "Provide 8–128 letters, digits, dots, underscores, colons, or hyphens."})
    try:
        execution, created = execute_agent(
            request.user,
            serializer.validated_data["agent_id"],
            serializer.validated_data["question"],
            idempotency_key,
            specialist_ids=serializer.validated_data.get("specialists"),
        )
    except AgentExecutionFailure as exc:
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.http_status)

    body = {
        "execution": AgentExecutionReadSerializer(execution).data,
        "idempotent_replay": not created,
    }
    if execution.status == "succeeded":
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    if execution.status == "running":
        return Response(body, status=status.HTTP_202_ACCEPTED)
    if execution.error_code in {"provider_disabled", "unsupported_provider", "configuration_incomplete", "invalid_provider_endpoint", "provider_unavailable"}:
        return Response(body, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(body, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_execution_detail(request, execution_id):
    execution = get_object_or_404(AgentExecution.objects.select_related(
        "workflow_disruption", "workflow_assessment_snapshot",
    ).prefetch_related("steps", "response_plans"), pk=execution_id, requested_by=request.user)
    return Response(AgentExecutionReadSerializer(execution).data)


def _disruption_workflow_question(disruption_id, assessment_id):
    return (
        "Prepare an evidence-grounded, advisory response analysis for ARES disruption UUID "
        f"{disruption_id}. Inspect that exact disruption with get_disruption and inspect only the exact "
        f"risk-assessment snapshot UUID {assessment_id} with get_risk_assessment_snapshot. "
        "Use specialist read-only ARES evidence for relevant supplier, inventory, logistics, and procurement context. "
        "Return up to three implementable recommendations, each tied to exact evidence references. State missing data, "
        "assumptions, and uncertainty. Do not infer causal impact, supplier capacity, prices, routes, or outcomes. "
        "Do not create, approve, or execute any operational record; each recommendation is for a human to review."
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AgentExecutionThrottle])
def disruption_workflows(request):
    if request.method == "GET":
        executions = AgentExecution.objects.filter(
            requested_by=request.user, workflow_disruption__isnull=False,
        ).select_related("workflow_disruption", "workflow_assessment_snapshot").prefetch_related(
            "steps", "response_plans",
        ).order_by("-created_at")[:50]
        return Response({"workflows": AgentExecutionReadSerializer(executions, many=True).data})

    serializer = DisruptionWorkflowRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    disruption = get_object_or_404(Disruption, pk=values["disruption_id"])
    assessment = RiskAssessmentSnapshot.objects.filter(
        pk=values["assessment_snapshot_id"], disruption=disruption,
    ).first()
    if assessment is None:
        raise ValidationError({"assessment_snapshot_id": "Choose an assessment snapshot belonging to this disruption."})
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise ValidationError({"Idempotency-Key": "Provide 8–128 letters, digits, dots, underscores, colons, or hyphens."})
    specialist_ids = values["specialists"]
    question = _disruption_workflow_question(disruption.pk, assessment.pk)
    try:
        execution, created = execute_agent(
            request.user, "coordinator", question, idempotency_key,
            specialist_ids=specialist_ids,
        )
    except AgentExecutionFailure as exc:
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.http_status)

    context_was_missing = execution.workflow_disruption_id is None
    if context_was_missing:
        execution.workflow_disruption = disruption
        execution.workflow_assessment_snapshot = assessment
        execution.save(update_fields=["workflow_disruption", "workflow_assessment_snapshot", "updated_at"])
        AuditEvent.objects.create(
            entity_type="supply_chain.agentexecution",
            entity_id=str(execution.pk), action="create",
            actor=request.user.get_username()[:120],
            changes={"before": None, "after": {
                "workflow_disruption_id": str(disruption.pk),
                "workflow_assessment_snapshot_id": str(assessment.pk),
                "status": execution.status,
                "agent_id": execution.agent_id,
            }},
        )
    elif execution.workflow_disruption_id != disruption.pk or execution.workflow_assessment_snapshot_id != assessment.pk:
        return Response({"error": {"code": "workflow_context_conflict", "message": "This idempotency key belongs to a different disruption workflow."}}, status=status.HTTP_409_CONFLICT)

    execution = AgentExecution.objects.select_related(
        "workflow_disruption", "workflow_assessment_snapshot",
    ).prefetch_related("steps", "response_plans").get(pk=execution.pk)
    body = {
        "execution": AgentExecutionReadSerializer(execution).data,
        "idempotent_replay": not created,
    }
    if execution.status == "succeeded":
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    if execution.status == "running":
        return Response(body, status=status.HTTP_202_ACCEPTED)
    if execution.error_code in {"provider_disabled", "unsupported_provider", "configuration_incomplete", "invalid_provider_endpoint", "provider_unavailable"}:
        return Response(body, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(body, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([AgentExecutionThrottle])
@transaction.atomic
def disruption_workflow_handoff(request, execution_id):
    serializer = DisruptionWorkflowHandoffSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    execution = get_object_or_404(
        AgentExecution.objects.select_for_update().select_related(
            "workflow_disruption", "workflow_assessment_snapshot",
        ),
        pk=execution_id, requested_by=request.user, agent_id="coordinator",
        workflow_disruption__isnull=False,
    )
    if execution.status != "succeeded":
        raise ValidationError({"execution": "Only a successful disruption workflow can be handed to response planning."})
    verified_reference_keys = {
        (reference.get("reference_type"), reference.get("reference_id"))
        for reference in execution.input_references
    }
    required_workflow_references = {
        ("disruption", str(execution.workflow_disruption_id)),
        ("risk_assessment", str(execution.workflow_assessment_snapshot_id)),
    }
    if not required_workflow_references.issubset(verified_reference_keys):
        raise ValidationError({
            "execution": "The workflow did not verify the exact disruption and assessment snapshot; it cannot be handed to response planning."
        })
    recommendations = execution.result.get("recommendations", [])
    recommendation_index = serializer.validated_data["recommendation_index"]
    if recommendation_index >= len(recommendations):
        raise ValidationError({"recommendation_index": "Choose a recommendation returned by this workflow."})
    recommendation = recommendations[recommendation_index]
    if not recommendation.get("requires_human_approval"):
        raise ValidationError({"recommendation_index": "The selected recommendation is not marked for human approval."})
    evidence = recommendation.get("evidence_references", [])
    if not evidence or any(reference not in execution.input_references for reference in evidence):
        raise ValidationError({"recommendation_index": "The recommendation does not contain verified workflow evidence."})

    existing = ResponsePlan.objects.filter(
        agent_execution=execution, source_recommendation_index=recommendation_index,
    ).first()
    if existing:
        return Response({"response_plan": ResponsePlanSerializer(existing).data, "idempotent_replay": True}, status=status.HTTP_200_OK)

    values = serializer.validated_data
    plan = ResponsePlan.objects.create(
        disruption=execution.workflow_disruption,
        assessment_snapshot=execution.workflow_assessment_snapshot,
        agent_execution=execution,
        source_recommendation_index=recommendation_index,
        agent_recommendation=recommendation,
        created_by=request.user,
        title=values["plan_title"],
        objective=recommendation["summary"],
        owner=values["plan_owner"],
        due_date=values.get("due_date"),
        status="draft",
    )
    action = ResponseAction.objects.create(
        plan=plan, position=1, title=values["action_title"],
        description=values.get("action_description", "") or recommendation["summary"],
        owner=values["action_owner"], due_date=values.get("due_date"), action_type="manual",
    )
    AuditEvent.objects.create(
        entity_type="supply_chain.responseplan", entity_id=str(plan.pk), action="create",
        actor=request.user.get_username()[:120],
        changes={"before": None, "after": {
            "status": plan.status, "disruption_id": str(plan.disruption_id),
            "assessment_snapshot_id": str(plan.assessment_snapshot_id),
            "agent_execution_id": str(execution.pk),
            "source_recommendation_index": recommendation_index,
            "recommendation": recommendation,
            "action": {"id": str(action.pk), "title": action.title, "owner": action.owner},
        }},
    )
    return Response({
        "response_plan": ResponsePlanSerializer(plan).data,
        "idempotent_replay": False,
    }, status=status.HTTP_201_CREATED)
