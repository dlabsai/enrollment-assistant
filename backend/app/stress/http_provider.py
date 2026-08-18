"""Loopback fake-provider services for HTTP connection-pool stress tests."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.stress.fake_embedding import (
    create_manifold_embedding,
    get_stress_embedding_bank,
    validate_stress_embedding_bank,
)
from app.stress.http_protocol import CLIENT_START_NS_HEADER, LLM_DELAY_PATH

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

_HTTP_CONFLICT = 409
_HTTP_UNPROCESSABLE_CONTENT = 422
_METRIC_SAMPLE_LIMIT = 100_000
_EMBEDDING_CACHE_SIZE = 1024
_MAX_KEEP_ALIVE_SECONDS = 300
_MAX_PADDING_BYTES = 1024 * 1024
_MAX_PORT = 65_535


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return round(ordered[index], 3)


def _float_list() -> list[float]:
    return []


def _connection_set() -> set[tuple[str, int]]:
    return set()


def _operation_counter() -> Counter[str]:
    return Counter()


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 3) if values else None,
    }


@dataclass
class ProviderMetrics:
    """Aggregate-only metrics for one fake-provider process."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: int = 0
    active: int = 0
    peak_active: int = 0
    errors: int = 0
    request_body_bytes: int = 0
    response_body_bytes: int = 0
    client_wait_ms: list[float] = field(default_factory=_float_list)
    service_ms: list[float] = field(default_factory=_float_list)
    connections: set[tuple[str, int]] = field(default_factory=_connection_set)
    operations: Counter[str] = field(default_factory=_operation_counter)

    @asynccontextmanager
    async def track(self, request: Request, *, operation: str) -> AsyncGenerator[None]:
        arrived_ns = time.perf_counter_ns()
        started_header = request.headers.get(CLIENT_START_NS_HEADER)
        wait_ms: float | None = None
        if started_header is not None:
            try:
                started_ns = int(started_header)
            except ValueError:
                started_ns = arrived_ns
            wait_ms = max(0, arrived_ns - started_ns) / 1_000_000
        peer = request.client
        try:
            request_body_bytes = int(request.headers.get("content-length", "0"))
        except ValueError:
            request_body_bytes = 0

        async with self.lock:
            self.requests += 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            self.operations[operation] += 1
            self.request_body_bytes += max(0, request_body_bytes)
            if wait_ms is not None and len(self.client_wait_ms) < _METRIC_SAMPLE_LIMIT:
                self.client_wait_ms.append(wait_ms)
            if peer is not None:
                self.connections.add((peer.host, peer.port))

        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            service_ms = max(0, time.perf_counter_ns() - arrived_ns) / 1_000_000
            async with self.lock:
                self.active -= 1
                if failed:
                    self.errors += 1
                if len(self.service_ms) < _METRIC_SAMPLE_LIMIT:
                    self.service_ms.append(service_ms)

    async def add_response_body(self, response: JSONResponse) -> None:
        async with self.lock:
            self.response_body_bytes += len(response.body)

    async def snapshot(self) -> dict[str, object]:
        async with self.lock:
            return {
                "schema_version": 1,
                "requests": self.requests,
                "active": self.active,
                "peak_active": self.peak_active,
                "unique_connections": len(self.connections),
                "client_wait_ms": _distribution(self.client_wait_ms),
                "service_ms": _distribution(self.service_ms),
                "errors": self.errors,
                "request_body_bytes": self.request_body_bytes,
                "response_body_bytes": self.response_body_bytes,
                "operations": dict(sorted(self.operations.items())),
            }

    async def reset(self) -> None:
        async with self.lock:
            if self.active:
                raise HTTPException(
                    status_code=_HTTP_CONFLICT,
                    detail="cannot reset metrics while provider requests are active",
                )
            self.requests = 0
            self.peak_active = 0
            self.errors = 0
            self.request_body_bytes = 0
            self.response_body_bytes = 0
            self.client_wait_ms.clear()
            self.service_ms.clear()
            self.connections.clear()
            self.operations.clear()


class LlmDelayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    profile_index: int = Field(ge=0)
    delay_ms: float = Field(ge=0, le=10 * 60 * 1000)
    request_padding: str = Field(default="", max_length=_MAX_PADDING_BYTES, pattern=r"^x*$")
    response_padding_bytes: int = Field(default=0, ge=0, le=_MAX_PADDING_BYTES)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    dimensions: int | None = None
    encoding_format: str | None = None


def _ensure_service_allowed() -> None:
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("stress HTTP provider services are forbidden in production")
    if not settings.STRESS_HTTP_PROVIDERS_ENABLED:
        raise RuntimeError("STRESS_HTTP_PROVIDERS_ENABLED must be true to start fake services")


@asynccontextmanager
async def _llm_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    _ensure_service_allowed()
    yield


def _register_controls(app: FastAPI, metrics: ProviderMetrics) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/metrics")
    async def get_metrics() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return await metrics.snapshot()

    @app.post("/reset")
    async def reset_metrics() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        await metrics.reset()
        return {"reset": True}


def create_llm_app() -> FastAPI:
    metrics = ProviderMetrics()
    app = FastAPI(title="Demo stress fake LLM", lifespan=_llm_lifespan)
    _register_controls(app, metrics)

    @app.post(LLM_DELAY_PATH)
    async def delay(  # pyright: ignore[reportUnusedFunction]
        payload: LlmDelayRequest, request: Request
    ) -> JSONResponse:
        async with metrics.track(request, operation=payload.role):
            await asyncio.sleep(payload.delay_ms / 1000)
            response = JSONResponse(
                {
                    "ok": True,
                    "role": payload.role,
                    "profile_index": payload.profile_index,
                    "response_padding": "x" * payload.response_padding_bytes,
                }
            )
            await metrics.add_response_body(response)
            return response

    return app


@asynccontextmanager
async def _embedding_lifespan(app: FastAPI) -> AsyncGenerator[None]:
    _ensure_service_allowed()
    bank_override = getattr(app.state, "embedding_bank_override", None)
    if bank_override is None:
        app.state.embedding_bank = await get_stress_embedding_bank()
        # The service needs the isolated DB only during startup; do not leave a pool slot open.
        from app.core.db import engine  # noqa: PLC0415

        await engine.dispose()
    else:
        app.state.embedding_bank = bank_override
    app.state.embedding_cache = {}
    yield


def create_embedding_app(*, embedding_bank: Sequence[Sequence[float]] | None = None) -> FastAPI:
    metrics = ProviderMetrics()
    app = FastAPI(title="Demo stress fake embeddings", lifespan=_embedding_lifespan)
    if embedding_bank is not None:
        app.state.embedding_bank_override = validate_stress_embedding_bank(embedding_bank)
    _register_controls(app, metrics)

    @app.post("/openai/deployments/{deployment}/embeddings")
    async def embeddings(  # pyright: ignore[reportUnusedFunction]
        deployment: str, payload: EmbeddingRequest, request: Request
    ) -> JSONResponse:
        inputs = payload.input if isinstance(payload.input, list) else [payload.input]
        if not inputs:
            raise HTTPException(
                status_code=_HTTP_UNPROCESSABLE_CONTENT, detail="embedding input cannot be empty"
            )
        if payload.dimensions not in {None, EMBEDDING_VECTOR_DIMENSIONS}:
            raise HTTPException(
                status_code=_HTTP_UNPROCESSABLE_CONTENT,
                detail=f"dimensions must be {EMBEDDING_VECTOR_DIMENSIONS}",
            )

        async with metrics.track(request, operation="embeddings"):
            bank = cast(tuple[tuple[float, ...], ...], request.app.state.embedding_bank)
            cache = cast(dict[bytes, tuple[float, ...]], request.app.state.embedding_cache)
            data: list[dict[str, object]] = []
            for index, value in enumerate(inputs):
                cache_key = hashlib.sha256(value.encode()).digest()
                vector = cache.get(cache_key)
                if vector is None:
                    vector = create_manifold_embedding(
                        value, bank, blend=settings.STRESS_FAKE_EMBEDDING_BLEND
                    )
                    if len(cache) < _EMBEDDING_CACHE_SIZE:
                        cache[cache_key] = vector
                data.append({"object": "embedding", "embedding": vector, "index": index})
            response = JSONResponse(
                {
                    "object": "list",
                    "data": data,
                    "model": payload.model or deployment,
                    "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
                }
            )
            await metrics.add_response_body(response)
            return response

    return app


llm_app = create_llm_app()
embedding_app = create_embedding_app()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.stress.http_provider",
        description="Serve one loopback fake provider for local connection-pool stress tests.",
        epilog=(
            "examples:\n"
            "  uv run -m app.stress.http_provider llm --port 8111\n"
            "  uv run -m app.stress.http_provider embedding --port 8112\n"
            "  uv run -m app.stress.http_provider llm --tls-cert-file cert.pem "
            "--tls-key-file key.pem"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="stress-http-provider 0.2")
    subparsers = parser.add_subparsers(dest="service", required=True)
    for service, default_port in (("llm", 8111), ("embedding", 8112)):
        service_parser = subparsers.add_parser(service, help=f"serve the fake {service} endpoint")
        service_parser.add_argument(
            "--host",
            choices=("127.0.0.1", "localhost", "::1"),
            default="127.0.0.1",
            help="loopback bind host; default: 127.0.0.1",
        )
        service_parser.add_argument(
            "--port", type=int, default=default_port, help=f"listen port; default: {default_port}"
        )
        service_parser.add_argument(
            "--access-log", action="store_true", help="log request paths; bodies are never logged"
        )
        service_parser.add_argument(
            "--keep-alive-seconds",
            type=int,
            default=30,
            help="server idle keep-alive timeout; default: 30",
        )
        service_parser.add_argument(
            "--tls-cert-file", help="PEM server certificate; requires --tls-key-file"
        )
        service_parser.add_argument(
            "--tls-key-file", help="PEM private key; requires --tls-cert-file"
        )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if not 1 <= args.port <= _MAX_PORT:
        raise SystemExit("error: --port must be between 1 and 65535")
    if not 1 <= args.keep_alive_seconds <= _MAX_KEEP_ALIVE_SECONDS:
        raise SystemExit("error: --keep-alive-seconds must be between 1 and 300")
    if bool(args.tls_cert_file) != bool(args.tls_key_file):
        raise SystemExit("error: --tls-cert-file and --tls-key-file must be provided together")
    selected_app = llm_app if args.service == "llm" else embedding_app
    uvicorn.run(
        selected_app,
        host=str(args.host),
        port=int(args.port),
        access_log=bool(args.access_log),
        log_level="info",
        timeout_keep_alive=int(args.keep_alive_seconds),
        ssl_certfile=args.tls_cert_file,
        ssl_keyfile=args.tls_key_file,
    )


if __name__ == "__main__":
    main()
