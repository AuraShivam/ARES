from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .data_imports import (
    ImportCommitError,
    ImportFileError,
    commit_preview,
    create_preview,
    serialize_import,
    template_metadata,
)
from .models import DataImport


@api_view(["GET"])
def import_templates(request):
    return Response(template_metadata())


@api_view(["GET"])
def imports_list(request):
    batches = DataImport.objects.all()[:100]
    return Response([serialize_import(batch) for batch in batches])


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def import_preview(request):
    try:
        batch = create_preview(
            entity_type=request.data.get("entity_type", ""),
            source_name=request.data.get("source_name", ""),
            duplicate_policy=request.data.get("duplicate_policy", "skip"),
            upload=request.FILES.get("file"),
        )
    except ImportFileError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serialize_import(batch, include_rows=True), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def import_detail(request, batch_id):
    batch = get_object_or_404(DataImport, pk=batch_id)
    return Response(serialize_import(batch, include_rows=True))


@api_view(["POST"])
def import_commit(request, batch_id):
    try:
        batch = commit_preview(batch_id)
    except ImportCommitError as exc:
        payload = {"detail": str(exc)}
        if exc.rows:
            payload["rows"] = exc.rows
        return Response(payload, status=status.HTTP_409_CONFLICT)
    except IntegrityError:
        return Response(
            {"detail": "A record changed while this import was committing. Review a new preview and retry."},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(serialize_import(batch, include_rows=True))
