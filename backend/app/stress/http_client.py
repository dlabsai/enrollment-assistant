"""Client helpers for loopback stress-provider services."""

from __future__ import annotations

import math
from typing import cast

from app.chat.provider_http import get_provider_http_client
from app.core.config import settings
from app.stress.http_protocol import LLM_DELAY_PATH


async def request_fake_llm_round(*, role: str, profile_index: int, delay_ms: float) -> None:
    """Occupy one shared-provider HTTP connection for a deterministic fake model round."""
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("stress HTTP providers are forbidden when ENVIRONMENT=production")
    if not settings.STRESS_HTTP_PROVIDERS_ENABLED or not settings.STRESS_FAKE_LLM_URL:
        raise RuntimeError("the fake LLM HTTP service is not configured")
    if profile_index < 0 or delay_ms < 0 or not math.isfinite(delay_ms):
        raise ValueError("fake LLM profile index and delay must be finite and non-negative")

    request_padding = "x" * settings.STRESS_FAKE_LLM_REQUEST_PADDING_BYTES
    response_padding_bytes = settings.STRESS_FAKE_LLM_RESPONSE_PADDING_BYTES
    client = get_provider_http_client(settings.STRESS_FAKE_LLM_URL)
    response = await client.post(
        f"{settings.STRESS_FAKE_LLM_URL}{LLM_DELAY_PATH}",
        json={
            "role": role,
            "profile_index": profile_index,
            "delay_ms": delay_ms,
            "request_padding": request_padding,
            "response_padding_bytes": response_padding_bytes,
        },
    )
    response.raise_for_status()
    raw_payload = cast(object, response.json())
    payload = cast(dict[str, object], raw_payload) if isinstance(raw_payload, dict) else {}
    response_padding = payload.get("response_padding")
    if (
        payload.get("ok") is not True
        or payload.get("role") != role
        or payload.get("profile_index") != profile_index
        or not isinstance(response_padding, str)
        or len(response_padding) != response_padding_bytes
    ):
        raise RuntimeError("fake LLM HTTP service returned an invalid response")
