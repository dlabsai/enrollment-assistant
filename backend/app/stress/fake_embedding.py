"""Token-free in-process or loopback-HTTP embeddings for isolated stress tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import TYPE_CHECKING, cast

import httpx
from openai import AsyncAzureOpenAI
from sqlalchemy import select

from app.core.config import settings
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS

if TYPE_CHECKING:
    from collections.abc import Sequence

_EMBEDDING_BANK_SIZE = 532
_EMBEDDING_CACHE_SIZE = 1024
_embedding_bank: tuple[tuple[float, ...], ...] | None = None
_embedding_bank_lock = asyncio.Lock()
_embedding_cache: dict[str, tuple[float, ...]] = {}


def _normalized(values: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(component * component for component in values))
    if norm == 0:
        raise RuntimeError("stress embedding bank contains a zero vector")
    return tuple(component / norm for component in values)


def validate_stress_embedding_bank(
    vectors: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], ...]:
    bank = tuple(tuple(float(component) for component in vector) for vector in vectors)
    if not bank:
        raise RuntimeError("stress embedding bank is empty")
    if any(len(vector) != EMBEDDING_VECTOR_DIMENSIONS for vector in bank):
        raise RuntimeError(
            f"stress embedding bank vectors must have {EMBEDDING_VECTOR_DIMENSIONS} dimensions"
        )
    return tuple(_normalized(vector) for vector in bank)


async def _load_embedding_bank() -> tuple[tuple[float, ...], ...]:
    # Imported lazily to keep ordinary application startup independent of stress-only code.
    from app.core.db import async_session_factory  # noqa: PLC0415
    from app.models import DocumentContentChunk  # noqa: PLC0415

    async with async_session_factory() as session:
        result = await session.execute(
            select(DocumentContentChunk.content_embedding)
            .order_by(DocumentContentChunk.id)
            .limit(_EMBEDDING_BANK_SIZE)
        )
    return validate_stress_embedding_bank(result.scalars().all())


async def get_stress_embedding_bank() -> tuple[tuple[float, ...], ...]:
    global _embedding_bank  # noqa: PLW0603

    if _embedding_bank is not None:
        return _embedding_bank
    async with _embedding_bank_lock:
        if _embedding_bank is None:
            _embedding_bank = await _load_embedding_bank()
    return _embedding_bank


def create_manifold_embedding(
    value: str, bank: tuple[tuple[float, ...], ...], *, blend: float
) -> tuple[float, ...]:
    if not 0 <= blend <= 1:
        raise RuntimeError("STRESS_FAKE_EMBEDDING_BLEND must be between 0 and 1")

    digest = hashlib.sha256(value.encode()).digest()
    seed = int.from_bytes(digest[:8])
    base_index = seed % len(bank)
    if len(bank) == 1 or blend == 0:
        return bank[base_index]

    other_index = (base_index + 1 + int.from_bytes(digest[8:16]) % (len(bank) - 1)) % len(bank)
    base = bank[base_index]
    other = bank[other_index]
    return _normalized(
        tuple(
            (1 - blend) * base_value + blend * other_value
            for base_value, other_value in zip(base, other, strict=True)
        )
    )


def _create_embedding_handler(
    bank_override: tuple[tuple[float, ...], ...] | None,
) -> httpx.AsyncBaseTransport:
    local_cache: dict[str, tuple[float, ...]] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        raw_input = payload.get("input", "")
        inputs: list[object] = (
            cast(list[object], raw_input) if isinstance(raw_input, list) else [raw_input]
        )
        bank = bank_override or await get_stress_embedding_bank()
        cache = local_cache if bank_override is not None else _embedding_cache
        data: list[dict[str, object]] = []
        for index, item in enumerate(inputs):
            value = str(item)
            vector = cache.get(value)
            if vector is None:
                vector = create_manifold_embedding(
                    value, bank, blend=settings.STRESS_FAKE_EMBEDDING_BLEND
                )
                if len(cache) < _EMBEDDING_CACHE_SIZE:
                    cache[value] = vector
            data.append({"object": "embedding", "embedding": vector, "index": index})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": data,
                "model": "stress-embedding",
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            },
        )

    return httpx.MockTransport(handle)


def create_stress_embedding_client(
    *, embedding_bank: Sequence[Sequence[float]] | None = None
) -> AsyncAzureOpenAI:
    """Create a fake embedding client backed by vectors from the isolated stress DB."""
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("stress fake embeddings are forbidden when ENVIRONMENT=production")
    bank = validate_stress_embedding_bank(embedding_bank) if embedding_bank is not None else None
    if bank is None and settings.STRESS_FAKE_EMBEDDING_URL:
        if not settings.STRESS_HTTP_PROVIDERS_ENABLED:
            raise RuntimeError("the fake embedding HTTP service is not enabled")
        from app.chat.provider_http import get_provider_http_client  # noqa: PLC0415

        return AsyncAzureOpenAI(
            azure_endpoint=settings.STRESS_FAKE_EMBEDDING_URL,
            api_key="stress-test-only",
            api_version="2024-10-21",
            http_client=get_provider_http_client(settings.STRESS_FAKE_EMBEDDING_URL),
        )
    return AsyncAzureOpenAI(
        azure_endpoint="http://stress-embedding.invalid",
        api_key="stress-test-only",
        api_version="2024-10-21",
        http_client=httpx.AsyncClient(transport=_create_embedding_handler(bank)),
    )
