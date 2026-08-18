from __future__ import annotations

import asyncio
import ssl
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import httpx

if TYPE_CHECKING:
    from collections.abc import Generator

from app.core.config import settings
from app.stress.http_protocol import CLIENT_START_NS_HEADER

_provider_http_clients: dict[str, httpx.AsyncClient] = {}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PROVIDER_REQUEST_START_NS_EXTENSION = "demo.provider_request_start_ns"


@dataclass(frozen=True, slots=True)
class ProviderResponseMetadata:
    provider_response_id: str
    service_tier: str | None
    duration_ms: float | None


_provider_response_capture: ContextVar[list[ProviderResponseMetadata] | None] = ContextVar(
    "provider_response_capture", default=None
)


@contextmanager
def capture_provider_response_metadata(
    *, enabled: bool
) -> Generator[list[ProviderResponseMetadata]]:
    """Capture privacy-safe Responses API metadata for the current agent run."""
    records: list[ProviderResponseMetadata] = []
    if not enabled:
        yield records
        return

    token = _provider_response_capture.set(records)
    try:
        yield records
    finally:
        _provider_response_capture.reset(token)


def _is_responses_request(request: httpx.Request) -> bool:
    return request.method == "POST" and request.url.path.rstrip("/").endswith("/responses")


async def mark_stress_request_start(request: httpx.Request) -> None:
    """Mark local fake-provider requests before HTTPX connection acquisition."""
    if (
        settings.STRESS_HTTP_PROVIDERS_ENABLED
        and settings.ENVIRONMENT != "production"
        and request.url.host in _LOOPBACK_HOSTS
    ):
        request.headers[CLIENT_START_NS_HEADER] = str(time.perf_counter_ns())


async def mark_provider_request_start(request: httpx.Request) -> None:
    """Start timing an in-scope Responses request before connection acquisition."""
    if _provider_response_capture.get() is not None and _is_responses_request(request):
        request.extensions[_PROVIDER_REQUEST_START_NS_EXTENSION] = time.perf_counter_ns()


async def capture_provider_response(response: httpx.Response) -> None:
    """Capture response ID, applied tier, and duration without retaining provider content."""
    records = _provider_response_capture.get()
    request = response.request
    if records is None or not response.is_success or not _is_responses_request(request):
        return
    if "text/event-stream" in response.headers.get("content-type", "").casefold():
        return

    await response.aread()
    ended_ns = time.perf_counter_ns()
    try:
        payload = cast(dict[str, Any], response.json())
    except TypeError, ValueError:
        return
    if not isinstance(payload, dict):
        return

    response_id = payload.get("id")
    if not isinstance(response_id, str) or not response_id.strip():
        return
    raw_service_tier = payload.get("service_tier")
    service_tier = (
        raw_service_tier.strip()
        if isinstance(raw_service_tier, str) and raw_service_tier.strip()
        else None
    )
    started_ns = request.extensions.get(_PROVIDER_REQUEST_START_NS_EXTENSION)
    duration_ms = (
        max((ended_ns - started_ns) / 1_000_000, 0.0) if isinstance(started_ns, int) else None
    )
    records.append(
        ProviderResponseMetadata(
            provider_response_id=response_id.strip(),
            service_tier=service_tier,
            duration_ms=duration_ms,
        )
    )


def _provider_tls_verification(provider_endpoint: str) -> bool | ssl.SSLContext:
    client_key = provider_endpoint.rstrip("/")
    fake_endpoints = {
        settings.STRESS_FAKE_LLM_URL.rstrip("/"),
        settings.STRESS_FAKE_EMBEDDING_URL.rstrip("/"),
    }
    if (
        settings.STRESS_HTTP_PROVIDERS_ENABLED
        and client_key.startswith("https://")
        and client_key in fake_endpoints
    ):
        if not settings.STRESS_FAKE_PROVIDER_CA_FILE:
            raise RuntimeError("HTTPS stress providers require an explicit CA file")
        return ssl.create_default_context(cafile=settings.STRESS_FAKE_PROVIDER_CA_FILE)
    return True


def get_provider_http_client(provider_endpoint: str) -> httpx.AsyncClient:
    """Return the process-local client shared by one provider endpoint."""
    client_key = provider_endpoint.rstrip("/")
    client = _provider_http_clients.get(client_key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=settings.LLM_REQUEST_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.PROVIDER_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=settings.PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS,
            ),
            event_hooks={
                "request": [mark_stress_request_start, mark_provider_request_start],
                "response": [capture_provider_response],
            },
            verify=_provider_tls_verification(client_key),
        )
        _provider_http_clients[client_key] = client
    return client


async def close_provider_http_clients() -> None:
    """Close and clear all process-local provider clients during shutdown."""
    clients = list(_provider_http_clients.values())
    _provider_http_clients.clear()
    if clients:
        await asyncio.gather(*(client.aclose() for client in clients))
