import logging

from django.db import IntegrityError, InterfaceError, OperationalError
from django.http import JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("ares.api")


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response

    request = context.get("request")
    logger.error(
        "Unhandled API exception",
        extra={"path": getattr(request, "path", "")},
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if isinstance(exc, IntegrityError):
        return Response(
            {"detail": "This change conflicts with an existing record. Refresh the data and try again."},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, (InterfaceError, OperationalError)):
        return Response(
            {"detail": "The database is temporarily unavailable. Try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(
        {"detail": "An unexpected API error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def api_not_found(request, exception=None):
    if request.path.startswith("/api/"):
        return JsonResponse({"detail": "API endpoint not found."}, status=status.HTTP_404_NOT_FOUND)
    from django.views.defaults import page_not_found

    return page_not_found(request, exception)


def api_server_error(request):
    if request.path.startswith("/api/"):
        return JsonResponse(
            {"detail": "An unexpected server error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    from django.views.defaults import server_error

    return server_error(request)
