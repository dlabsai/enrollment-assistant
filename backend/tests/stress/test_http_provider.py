from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncAzureOpenAI
from pydantic_ai import Agent

from app.core.config import Settings, settings
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.stress.fake_model import create_stress_model
from app.stress.http_client import request_fake_llm_round
from app.stress.http_protocol import CLIENT_START_NS_HEADER
from app.stress.http_provider import create_embedding_app, create_llm_app

if TYPE_CHECKING:
    from pathlib import Path


def test_settings_reject_stress_http_providers_in_production() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        Settings(ENVIRONMENT="production", STRESS_HTTP_PROVIDERS_ENABLED=True)


def test_settings_reject_non_loopback_stress_provider_url() -> None:
    with pytest.raises(ValueError, match="loopback HTTP"):
        Settings(
            ENVIRONMENT="local",
            STRESS_HTTP_PROVIDERS_ENABLED=True,
            STRESS_FAKE_LLM_URL="https://provider.example/v1",
        )


def test_settings_require_explicit_http_provider_enablement() -> None:
    with pytest.raises(ValueError, match="must be true"):
        Settings(ENVIRONMENT="local", STRESS_FAKE_LLM_URL="http://127.0.0.1:8111")


def test_settings_require_ca_file_for_https_stress_provider() -> None:
    with pytest.raises(ValueError, match="require STRESS_FAKE_PROVIDER_CA_FILE"):
        Settings(
            ENVIRONMENT="local",
            STRESS_HTTP_PROVIDERS_ENABLED=True,
            STRESS_FAKE_LLM_URL="https://127.0.0.1:8111",
        )


def test_settings_normalize_loopback_stress_provider_urls(tmp_path: Path) -> None:
    configured = Settings(
        ENVIRONMENT="local",
        STRESS_HTTP_PROVIDERS_ENABLED=True,
        STRESS_FAKE_LLM_URL="http://localhost:8111/",
    )
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("test CA")
    https_configured = Settings(
        ENVIRONMENT="local",
        STRESS_HTTP_PROVIDERS_ENABLED=True,
        STRESS_FAKE_LLM_URL="https://localhost:8111/",
        STRESS_FAKE_PROVIDER_CA_FILE=str(ca_file),
    )

    assert configured.STRESS_FAKE_LLM_URL == "http://localhost:8111"
    assert https_configured.STRESS_FAKE_LLM_URL == "https://localhost:8111"
    assert str(ca_file.resolve()) == https_configured.STRESS_FAKE_PROVIDER_CA_FILE


def test_settings_reject_stress_payloads_in_production() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        Settings(
            ENVIRONMENT="production",
            STRESS_HTTP_PROVIDERS_ENABLED=True,
            STRESS_FAKE_LLM_REQUEST_PADDING_BYTES=128,
        )


def test_settings_validate_provider_http_limits() -> None:
    with pytest.raises(ValueError, match="must be between zero"):
        Settings(PROVIDER_HTTP_MAX_CONNECTIONS=5, PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS=6)


@pytest.mark.asyncio
async def test_fake_llm_service_delays_and_reports_aggregate_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    app = create_llm_app()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        started_ns = time.perf_counter_ns() - 5_000_000
        response = await client.post(
            "/v1/delay",
            headers={CLIENT_START_NS_HEADER: str(started_ns)},
            json={
                "role": "chatbot",
                "profile_index": 7,
                "delay_ms": 10,
                "request_padding": "x" * 128,
                "response_padding_bytes": 64,
            },
        )
        metrics = (await client.get("/metrics")).json()

        assert response.status_code == 200
        assert len(response.json()["response_padding"]) == 64
        assert metrics["requests"] == 1
        assert metrics["peak_active"] == 1
        assert metrics["unique_connections"] == 1
        assert metrics["operations"] == {"chatbot": 1}
        assert metrics["client_wait_ms"]["samples"] == 1
        assert metrics["client_wait_ms"]["p50"] >= 5
        assert metrics["service_ms"]["p50"] >= 10
        assert metrics["errors"] == 0
        assert metrics["request_body_bytes"] >= 128
        assert metrics["response_body_bytes"] >= 64
        assert "request_padding" not in metrics
        assert "response_padding" not in metrics

        reset = await client.post("/reset")
        assert reset.status_code == 200
        assert (await client.get("/metrics")).json()["requests"] == 0


@pytest.mark.asyncio
async def test_fake_llm_rejects_non_synthetic_padding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    app = create_llm_app()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/delay",
            json={
                "role": "chatbot",
                "profile_index": 0,
                "delay_ms": 0,
                "request_padding": "not synthetic",
                "prompt": "must be rejected",
            },
        )
        metrics = (await client.get("/metrics")).json()

    assert response.status_code == 422
    assert metrics["requests"] == 0


@pytest.mark.asyncio
async def test_fake_llm_metrics_cannot_reset_during_active_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    app = create_llm_app()
    metrics: dict[str, object] = {}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        request_task = asyncio.create_task(
            client.post("/v1/delay", json={"role": "guardrail", "profile_index": 0, "delay_ms": 50})
        )
        for _ in range(100):
            metrics = (await client.get("/metrics")).json()
            if metrics["active"] == 1:
                break
            await asyncio.sleep(0)

        reset = await client.post("/reset")
        response = await request_task

        assert metrics["active"] == 1
        assert reset.status_code == 409
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_fake_embedding_service_uses_azure_protocol_and_vector_bank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    second = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    first[0] = 1.0
    second[1] = 1.0
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    monkeypatch.setattr(settings, "STRESS_FAKE_EMBEDDING_BLEND", 0.05)
    app = create_embedding_app(embedding_bank=[first, second])

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http_client,
    ):
        client = AsyncAzureOpenAI(
            azure_endpoint="http://testserver",
            api_key="stress-test-only",
            api_version="2024-10-21",
            http_client=http_client,
        )
        response = await client.embeddings.create(
            input="admissions stress query",
            model="text-embedding-3-large",
            dimensions=EMBEDDING_VECTOR_DIMENSIONS,
        )
        metrics = (await http_client.get("/metrics")).json()

    vector = response.data[0].embedding
    assert len(vector) == EMBEDDING_VECTOR_DIMENSIONS
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert sum(value != 0 for value in vector) == 2
    assert metrics["requests"] == 1
    assert metrics["operations"] == {"embeddings": 1}
    assert metrics["errors"] == 0


@pytest.mark.asyncio
async def test_fake_llm_client_sends_and_validates_synthetic_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://127.0.0.1:8111/v1/delay"),
        json={"ok": True, "role": "chatbot", "profile_index": 4, "response_padding": "xxx"},
    )
    client = AsyncMock()
    client.post.return_value = response
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    monkeypatch.setattr(settings, "STRESS_FAKE_LLM_URL", "https://127.0.0.1:8111")
    monkeypatch.setattr(settings, "STRESS_FAKE_LLM_REQUEST_PADDING_BYTES", 5)
    monkeypatch.setattr(settings, "STRESS_FAKE_LLM_RESPONSE_PADDING_BYTES", 3)

    def get_client(_url: str) -> AsyncMock:
        return client

    monkeypatch.setattr("app.stress.http_client.get_provider_http_client", get_client)

    await request_fake_llm_round(role="chatbot", profile_index=4, delay_ms=12.5)

    payload = client.post.await_args.kwargs["json"]
    assert payload == {
        "role": "chatbot",
        "profile_index": 4,
        "delay_ms": 12.5,
        "request_padding": "xxxxx",
        "response_padding_bytes": 3,
    }


@pytest.mark.asyncio
async def test_stress_model_uses_http_service_even_with_zero_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_round = AsyncMock()
    monkeypatch.setattr(settings, "STRESS_HTTP_PROVIDERS_ENABLED", True)
    monkeypatch.setattr(settings, "STRESS_FAKE_LLM_URL", "http://127.0.0.1:8111")
    monkeypatch.setattr(settings, "STRESS_FAKE_LATENCY_SCALE", 0)
    monkeypatch.setattr("app.stress.http_client.request_fake_llm_round", request_round)

    agent = Agent(create_stress_model("stress/chatbot/3"))
    result = await agent.run("hi")

    assert result.output == "Hello! How can I help you today?"
    request_round.assert_awaited_once_with(role="chatbot", profile_index=3, delay_ms=0.0)
