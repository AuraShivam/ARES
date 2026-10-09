"""Approval-gated dry-run and webhook execution for response action items."""

import hashlib
import json
import os
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from .models import AuditEvent, ResponseAction, ResponseActionExecution


MAX_WEBHOOK_BYTES = 64 * 1024
MAX_LIVE_ATTEMPTS = 3
EXECUTION_LEASE_MINUTES = 15


class ActionExecutionConflict(APIException):
    status_code = 409
    default_detail = "This idempotency key was already used for a different action request."
    default_code = "idempotency_conflict"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _request_digest(action, mode):
    identity = {
        "action_id": str(action.pk),
        "mode": mode,
        "action_type": action.action_type,
        "title": action.title,
        "description": action.description,
        "plan_id": str(action.plan_id),
        "disruption_id": str(action.plan.disruption_id),
        "execution_payload": action.execution_payload,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _webhook_configuration():
    endpoint = os.getenv("ARES_ACTION_WEBHOOK_URL", "").strip()
    allowed_hosts = {
        host.strip().casefold().rstrip(".")
        for host in os.getenv("ARES_ACTION_WEBHOOK_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
        raise ValidationError("A live webhook requires a configured HTTPS endpoint without embedded credentials or fragments.")
    if host not in allowed_hosts:
        raise ValidationError("The configured webhook host is not in ARES_ACTION_WEBHOOK_ALLOWED_HOSTS.")
    return endpoint


def _post_webhook(action, execution):
    endpoint = _webhook_configuration()
    body = {
        "idempotency_key": execution.idempotency_key,
        "action": {
            "id": str(action.pk),
            "title": action.title,
            "description": action.description,
            "payload": action.execution_payload,
        },
        "plan": {"id": str(action.plan_id), "title": action.plan.title},
        "disruption": {"id": str(action.plan.disruption_id), "title": action.plan.disruption.title},
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_WEBHOOK_BYTES:
        raise ValidationError("The configured response action payload exceeds the 64 KB limit.")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": execution.idempotency_key,
        "User-Agent": "ARES/1.0 (approved-response-action)",
    }
    token = os.getenv("ARES_ACTION_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint, data=encoded, headers=headers, method="POST")
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=10) as response:
            status_code = response.status
            response_body = response.read(MAX_WEBHOOK_BYTES + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RuntimeError("webhook_redirect_blocked") from exc
        raise RuntimeError(f"webhook_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("webhook_transport_error") from exc

    if not 200 <= status_code < 300:
        raise RuntimeError(f"webhook_http_{status_code}")
    if len(response_body) > MAX_WEBHOOK_BYTES:
        raise RuntimeError("webhook_response_too_large")
    return {
        "http_status": status_code,
        "response_bytes": len(response_body),
        "response_sha256": hashlib.sha256(response_body).hexdigest(),
    }


def _audit_execution(execution, action_name, before=None, actor=None):
    AuditEvent.objects.create(
        entity_type="supply_chain.responseactionexecution",
        entity_id=str(execution.pk),
        action=action_name,
        actor=actor or execution.requested_by,
        changes={
            "before": before,
            "after": {
                "action_id": str(execution.action_id),
                "idempotency_key": execution.idempotency_key,
                "adapter": execution.adapter,
                "mode": execution.mode,
                "status": execution.status,
                "attempt_count": execution.attempt_count,
                "requested_by": execution.requested_by,
                "approved_by": execution.approved_by,
                "result_summary": execution.result_summary,
                "error_code": execution.error_code,
            },
        },
    )


def _existing_execution(key, action, digest):
    existing = ResponseActionExecution.objects.select_for_update().filter(idempotency_key=key).first()
    if existing is None:
        return None
    if existing.action_id != action.pk or existing.request_hash != digest:
        raise ActionExecutionConflict()
    return existing


def execute_action(action_id, *, idempotency_key, requested_by, live=False):
    key = (idempotency_key or "").strip()
    if not key or len(key) > 128:
        raise ValidationError({"idempotency_key": "Provide an Idempotency-Key header between 1 and 128 characters."})
    mode = "live" if live else "dry_run"
    should_dispatch = False

    try:
        with transaction.atomic():
            action = ResponseAction.objects.select_for_update().select_related(
                "plan", "plan__disruption",
            ).get(pk=action_id)
            digest = _request_digest(action, mode)
            existing = _existing_execution(key, action, digest)
            if existing is not None:
                if not live or existing.status in {"simulated", "succeeded"}:
                    return existing, True
                now = timezone.now()
                lease_expired = (
                    existing.status == "running"
                    and existing.started_at <= now - timedelta(minutes=EXECUTION_LEASE_MINUTES)
                )
                if existing.status == "running" and not lease_expired:
                    return existing, True
                if existing.attempt_count >= MAX_LIVE_ATTEMPTS:
                    if lease_expired:
                        before = {"status": "running", "attempt_count": existing.attempt_count}
                        existing.status = "failed"
                        existing.error_code = "execution_lease_expired"
                        existing.result_summary = {"performed": "unknown", "detail": "Execution stopped without a confirmed result."}
                        existing.completed_at = now
                        existing.save(update_fields=["status", "error_code", "result_summary", "completed_at", "updated_at"])
                        _audit_execution(existing, "update", before=before, actor=requested_by)
                    return existing, True
                if action.plan.status != "active":
                    raise ValidationError("A response plan must remain active for a failed live execution to be retried.")
                if action.status not in {"pending", "in_progress"}:
                    raise ValidationError({"status": "Only pending or in-progress actions can execute."})
                if not settings.ARES_ACTION_EXECUTION_ENABLED:
                    raise ValidationError("Live action execution is disabled. Set ARES_ACTION_EXECUTION_ENABLED=true after configuring the adapter.")
                _webhook_configuration()
                before = {"status": existing.status, "attempt_count": existing.attempt_count}
                existing.status = "running"
                existing.attempt_count += 1
                existing.approved_by = requested_by
                existing.error_code = ""
                existing.result_summary = {}
                existing.started_at = now
                existing.completed_at = None
                existing.save(update_fields=[
                    "status", "attempt_count", "approved_by", "error_code", "result_summary",
                    "started_at", "completed_at", "updated_at",
                ])
                _audit_execution(existing, "update", before=before, actor=requested_by)
                execution = existing
                should_dispatch = True
            else:
                if action.plan.status != "active":
                    raise ValidationError("A response plan must be approved and started before an action can execute.")
                if action.status not in {"pending", "in_progress"}:
                    raise ValidationError({"status": "Only pending or in-progress actions can execute."})
                if live:
                    if not settings.ARES_ACTION_EXECUTION_ENABLED:
                        raise ValidationError("Live action execution is disabled. Set ARES_ACTION_EXECUTION_ENABLED=true after configuring the adapter.")
                    if action.action_type != "webhook":
                        raise ValidationError("Live execution is available only for actions configured with the webhook adapter.")
                    _webhook_configuration()
                    prior_live = ResponseActionExecution.objects.filter(action=action, mode="live").order_by("-created_at").first()
                    if prior_live and prior_live.status == "succeeded":
                        raise ValidationError("This action already has a successful live execution; create a new approved action for another run.")
                    if prior_live and prior_live.status in {"failed", "running"}:
                        raise ValidationError({
                            "idempotency_key": "Retry the existing live execution with its original Idempotency-Key; use a new action for a separate operation.",
                        })

                now = timezone.now()
                execution = ResponseActionExecution.objects.create(
                    action=action,
                    idempotency_key=key,
                    request_hash=digest,
                    adapter=action.action_type,
                    mode=mode,
                    status="running" if live else "simulated",
                    attempt_count=1 if live else 0,
                    requested_by=requested_by,
                    approved_by=requested_by if live else "",
                    result_summary={} if live else {
                        "performed": False,
                        "detail": "Dry run only; no external or operational side effect was performed.",
                        "payload_sha256": hashlib.sha256(
                            json.dumps(action.execution_payload, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                    },
                    started_at=now,
                    completed_at=None if live else now,
                )
                _audit_execution(execution, "create")
                should_dispatch = live
    except ResponseAction.DoesNotExist as exc:
        raise ValidationError("Response action not found.") from exc
    except IntegrityError:
        existing = ResponseActionExecution.objects.filter(idempotency_key=key).first()
        if existing is None:
            raise
        if existing.action_id != action_id or existing.request_hash != digest:
            raise ActionExecutionConflict()
        return existing, True

    if not live:
        return execution, False
    if not should_dispatch:
        return execution, True

    try:
        summary = _post_webhook(action, execution)
    except Exception as exc:
        execution.status = "failed"
        execution.error_code = str(exc)[:80] if isinstance(exc, RuntimeError) else type(exc).__name__[:80]
        execution.result_summary = {"performed": "unknown", "detail": "Adapter did not confirm success."}
    else:
        execution.status = "succeeded"
        execution.error_code = ""
        execution.result_summary = {"performed": True, **summary}
    execution.completed_at = timezone.now()
    before = {"status": "running"}
    execution.save(update_fields=["status", "error_code", "result_summary", "completed_at", "updated_at"])
    _audit_execution(execution, "update", before=before, actor=requested_by)
    return execution, False
