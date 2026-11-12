"""Small provider boundary for bounded, structured agent responses.

The default provider is disabled. The OpenAI Responses adapter is only used
when an operator configures it and opts into external processing.
"""

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings


MAX_RESPONSE_BYTES = 1_000_000
RETRYABLE_HTTP_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class ProviderFailure(Exception):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.attempt_count = 0


@dataclass(frozen=True)
class ProviderConfiguration:
    provider: str
    model: str
    api_key: str
    base_url: str
    timeout_seconds: int
    max_tool_calls: int
    max_output_tokens: int


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _valid_endpoint(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return False
        return True
    except ValueError:
        return False


def provider_readiness():
    """Return public configuration state without exposing secrets or endpoint URLs."""
    provider = getattr(settings, "ARES_AGENT_PROVIDER", "disabled") or "disabled"
    model = getattr(settings, "ARES_AGENT_MODEL", "")
    api_key = getattr(settings, "ARES_AGENT_API_KEY", "")
    base_url = getattr(settings, "ARES_AGENT_API_BASE_URL", "")
    external_enabled = bool(getattr(settings, "ARES_AGENT_EXTERNAL_PROCESSING_ENABLED", False))

    missing = []
    if provider == "disabled":
        return {
            "status": "unavailable",
            "code": "provider_disabled",
            "provider": provider,
            "model": "",
            "external_processing_enabled": external_enabled,
            "missing_configuration": ["ARES_AGENT_PROVIDER"],
        }
    if provider != "openai_responses":
        return {
            "status": "unavailable",
            "code": "unsupported_provider",
            "provider": "unsupported",
            "model": "",
            "external_processing_enabled": external_enabled,
            "missing_configuration": ["ARES_AGENT_PROVIDER"],
        }
    if not external_enabled:
        missing.append("ARES_AGENT_EXTERNAL_PROCESSING_ENABLED")
    if not model:
        missing.append("ARES_AGENT_MODEL")
    if not api_key:
        missing.append("ARES_AGENT_API_KEY")
    if not base_url:
        missing.append("ARES_AGENT_API_BASE_URL")
    elif not _valid_endpoint(base_url):
        return {
            "status": "unavailable",
            "code": "invalid_provider_endpoint",
            "provider": provider,
            "model": model,
            "external_processing_enabled": external_enabled,
            "missing_configuration": ["ARES_AGENT_API_BASE_URL must be an HTTPS URL (HTTP is allowed only for localhost)."],
        }
    if missing:
        return {
            "status": "unavailable",
            "code": "configuration_incomplete",
            "provider": provider,
            "model": model,
            "external_processing_enabled": external_enabled,
            "missing_configuration": missing,
        }
    return {
        "status": "configured",
        "code": "configured",
        "provider": provider,
        "model": model,
        "external_processing_enabled": True,
        "missing_configuration": [],
    }


def provider_configuration():
    readiness = provider_readiness()
    if readiness["status"] != "configured":
        return None
    return ProviderConfiguration(
        provider=readiness["provider"],
        model=readiness["model"],
        api_key=settings.ARES_AGENT_API_KEY,
        base_url=settings.ARES_AGENT_API_BASE_URL.rstrip("/"),
        timeout_seconds=settings.ARES_AGENT_TIMEOUT_SECONDS,
        max_tool_calls=settings.ARES_AGENT_MAX_TOOL_CALLS,
        max_output_tokens=settings.ARES_AGENT_MAX_OUTPUT_TOKENS,
    )


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter using stdlib HTTP and strict JSON output."""

    provider_id = "openai_responses"

    def __init__(self, configuration):
        self.configuration = configuration
        self._opener = build_opener(_NoRedirect())

    def create_response(self, input_items, tool_definitions, output_schema, timeout_seconds, *, instructions):
        endpoint = f"{self.configuration.base_url}/responses"
        parsed_endpoint = urlsplit(endpoint)
        endpoint = urlunsplit((parsed_endpoint.scheme, parsed_endpoint.netloc, parsed_endpoint.path, "", ""))
        payload = {
            "model": self.configuration.model,
            "instructions": instructions,
            "input": input_items,
            "tools": tool_definitions,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
            "max_output_tokens": self.configuration.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ares_agent_execution_result",
                    "strict": True,
                    "schema": output_schema,
                }
            },
        }
        request = Request(
            endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.configuration.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ARES-agent-runtime/1.0",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=max(1, timeout_seconds)) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP_STATUSES
            if exc.code == 401 or exc.code == 403:
                raise ProviderFailure("provider_auth_failed", "The configured provider rejected authentication.") from None
            if exc.code == 429:
                raise ProviderFailure("provider_rate_limited", "The configured provider rate limited this request.", retryable=True) from None
            if retryable:
                raise ProviderFailure("provider_temporarily_unavailable", "The configured provider is temporarily unavailable.", retryable=True) from None
            raise ProviderFailure("provider_request_rejected", "The configured provider rejected the request.") from None
        except URLError:
            raise ProviderFailure("provider_connection_failed", "ARES could not reach the configured provider.", retryable=True) from None
        except TimeoutError:
            raise ProviderFailure("provider_timeout", "The configured provider did not respond before the timeout.", retryable=True) from None

        if len(body) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("provider_response_too_large", "The configured provider returned an oversized response.")
        try:
            response_data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderFailure("provider_invalid_response", "The configured provider returned invalid JSON.") from None
        if not isinstance(response_data, dict) or not isinstance(response_data.get("output"), list):
            raise ProviderFailure("provider_invalid_response", "The configured provider returned an unexpected response shape.")
        return response_data


def get_provider():
    configuration = provider_configuration()
    if configuration is None:
        return None
    if configuration.provider == "openai_responses":
        return OpenAIResponsesProvider(configuration)
    return None


def bounded_retry(call, *, attempts=2, deadline):
    """Retry transient provider failures once, bounded by the execution deadline."""
    last_error = None
    for attempt in range(max(1, attempts)):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFailure("execution_timeout", "Agent execution exceeded its configured timeout.")
        try:
            return call(remaining), attempt + 1
        except ProviderFailure as exc:
            last_error = exc
            if not exc.retryable or attempt + 1 >= attempts:
                exc.attempt_count = attempt + 1
                raise
            time.sleep(min(0.25 * (attempt + 1), max(0, deadline - time.monotonic())))
    raise last_error or ProviderFailure("provider_failure", "The provider request failed.")
