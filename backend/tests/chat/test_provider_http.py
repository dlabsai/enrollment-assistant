from __future__ import annotations

import ssl
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.chat import provider_http

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class _TrackingAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.was_read = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.was_read = True
        yield b'data: {"type":"response.completed"}\n\n'

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_provider_client_applies_configured_limits_and_marks_loopback_stress_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await provider_http.close_provider_http_clients()
    client = MagicMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(provider_http.settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(provider_http.settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    monkeypatch.setattr(provider_http.settings, "PROVIDER_HTTP_MAX_CONNECTIONS", 17)
    monkeypatch.setattr(provider_http.settings, "PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS", 9)
    monkeypatch.setattr(provider_http.httpx, "AsyncClient", constructor)

    created = provider_http.get_provider_http_client("http://127.0.0.1:8111/")
    reused = provider_http.get_provider_http_client("http://127.0.0.1:8111")

    assert created is client
    assert reused is client
    kwargs = constructor.call_args.kwargs
    limits = kwargs["limits"]
    assert isinstance(limits, httpx.Limits)
    assert limits.max_connections == 17
    assert limits.max_keepalive_connections == 9
    assert kwargs["verify"] is True
    assert kwargs["event_hooks"] == {
        "request": [
            provider_http.mark_stress_request_start,
            provider_http.mark_provider_request_start,
        ],
        "response": [provider_http.capture_provider_response],
    }

    hook = kwargs["event_hooks"]["request"][0]
    request = httpx.Request("POST", "http://127.0.0.1:8111/v1/delay")
    await hook(request)
    assert int(request.headers[provider_http.CLIENT_START_NS_HEADER]) > 0

    await provider_http.close_provider_http_clients()
    client.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_provider_client_trusts_explicit_ca_only_for_fake_https_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await provider_http.close_provider_http_clients()
    client = MagicMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    constructor = MagicMock(return_value=client)
    ssl_context = MagicMock(spec=ssl.SSLContext)
    create_context = MagicMock(return_value=ssl_context)
    monkeypatch.setattr(provider_http.settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(provider_http.settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    monkeypatch.setattr(provider_http.settings, "STRESS_FAKE_LLM_URL", "https://127.0.0.1:8111")
    monkeypatch.setattr(provider_http.settings, "STRESS_FAKE_EMBEDDING_URL", "")
    ca_file = tmp_path / "ca.pem"
    monkeypatch.setattr(provider_http.settings, "STRESS_FAKE_PROVIDER_CA_FILE", str(ca_file))
    monkeypatch.setattr(provider_http.ssl, "create_default_context", create_context)
    monkeypatch.setattr(provider_http.httpx, "AsyncClient", constructor)

    provider_http.get_provider_http_client("https://127.0.0.1:8111")

    create_context.assert_called_once_with(cafile=str(ca_file))
    assert constructor.call_args.kwargs["verify"] is ssl_context
    await provider_http.close_provider_http_clients()


@pytest.mark.asyncio
async def test_provider_client_captures_in_scope_responses_metadata_without_content() -> None:
    with provider_http.capture_provider_response_metadata(enabled=True) as records:
        request = httpx.Request("POST", "https://provider.example/openai/v1/responses")
        await provider_http.mark_provider_request_start(request)
        response = httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/json"},
            json={
                "id": "resp-123",
                "service_tier": "priority",
                "output": [{"content": "sensitive response content"}],
            },
        )

        await provider_http.capture_provider_response(response)

    assert len(records) == 1
    assert records[0].provider_response_id == "resp-123"
    assert records[0].service_tier == "priority"
    assert records[0].duration_ms is not None
    assert records[0].duration_ms >= 0
    assert not hasattr(records[0], "output")


@pytest.mark.asyncio
async def test_provider_client_does_not_read_streamed_response_metadata() -> None:
    with provider_http.capture_provider_response_metadata(enabled=True) as records:
        request = httpx.Request("POST", "https://provider.example/openai/v1/responses")
        await provider_http.mark_provider_request_start(request)
        stream = _TrackingAsyncByteStream()
        response = httpx.Response(
            200, request=request, headers={"content-type": "text/event-stream"}, stream=stream
        )

        await provider_http.capture_provider_response(response)

    assert records == []
    assert stream.was_read is False
    assert response.is_stream_consumed is False
    await response.aclose()


@pytest.mark.asyncio
async def test_provider_client_does_not_mark_real_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_http.settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(provider_http.settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    request = httpx.Request("POST", "https://provider.example/v1/responses")

    await provider_http.mark_stress_request_start(request)

    assert provider_http.CLIENT_START_NS_HEADER not in request.headers
