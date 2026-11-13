"""Authenticated status, execution, and read-only tool endpoints."""

import re

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from ..agentic_data_readiness import build_agent_data_readiness
from ..models import AgentExecution
from .contracts import SPECIALIST_AGENT_IDS
from .providers import provider_readiness
from .runtime import AgentExecutionFailure, execute_agent
from .serializers import AgentExecutionReadSerializer, AgentExecutionRequestSerializer
from .tools import list_tools


class AgentExecutionThrottle(UserRateThrottle):
    scope = "ares_agent_execution"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


@api_view(["GET"])
def data_readiness(request):
    """Report current operational-data coverage for planned AI capabilities."""
    return Response(build_agent_data_readiness())


@api_view(["GET"])
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
        "provider_reachability_checked": False,
    })


@api_view(["GET"])
def agent_tools(request):
    return Response({"tools": list_tools()})


@api_view(["GET", "POST"])
@throttle_classes([AgentExecutionThrottle])
def agent_executions(request):
    if request.method == "GET":
        executions = AgentExecution.objects.filter(requested_by=request.user).prefetch_related("steps").order_by("-created_at")[:50]
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
def agent_execution_detail(request, execution_id):
    execution = get_object_or_404(AgentExecution.objects.prefetch_related("steps"), pk=execution_id, requested_by=request.user)
    return Response(AgentExecutionReadSerializer(execution).data)
