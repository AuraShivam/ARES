"""Authenticated read-only endpoints for the agentic foundation."""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..agentic_data_readiness import build_agent_data_readiness


@api_view(["GET"])
def data_readiness(request):
    """Report current operational-data coverage for planned AI capabilities."""
    return Response(build_agent_data_readiness())
