"""Authenticated SSE chat burst harness for isolated deployed stress environments."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import httpx

_PROFILE_PATH = Path(__file__).parent / "profiles" / "synthetic_chat_timings.json"
_HTTP_OK = 200


@dataclass(frozen=True)
class RequestResult:
    status: int | None
    conversation_ms: float | None
    assistant_ms: float | None
    close_ms: float
    error: str | None


@dataclass(frozen=True)
class LevelResult:
    concurrency: int
    round: int
    errors: int
    assistant_p50_ms: float | None
    assistant_p95_ms: float | None
    assistant_p99_ms: float | None
    close_p95_ms: float
    wall_ms: float
    client_cpu_percent: float
    health_samples: int
    health_errors: int
    health_p95_ms: float
    health_max_ms: float


def _elapsed_ms(started_ns: int) -> float:
    elapsed_ns = time.perf_counter_ns() - started_ns
    if elapsed_ns < 0:
        raise RuntimeError("monotonic clock moved backwards")
    return elapsed_ns / 1_000_000


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _normalize_base_url(value: str, *, allow_remote: bool, isolated_db_ack: bool) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "--base-url must be an HTTP(S) origin without a path, query, or fragment"
        )
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and not (
        allow_remote and isolated_db_ack
    ):
        raise RuntimeError("remote target requires --allow-remote and --isolated-db-ack")
    return base_url


async def _send_chat(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    gate: asyncio.Event,
    ready: asyncio.Event,
    profile_index: int,
) -> RequestResult:
    ready.set()
    await gate.wait()
    started_ns = time.perf_counter_ns()
    conversation_ms: float | None = None
    assistant_ms: float | None = None
    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/messages/internal/stream",
            headers={"Origin": base_url},
            json={
                "user_prompt": f"hi [stress-profile:{profile_index}]",
                "chatbot_model": f"stress/chatbot/{profile_index}",
                "guardrail_model": f"stress/guardrail/{profile_index}",
            },
        ) as response:
            async for line in response.aiter_lines():
                if line == "event: conversation" and conversation_ms is None:
                    conversation_ms = _elapsed_ms(started_ns)
                elif line == "event: assistant_message" and assistant_ms is None:
                    assistant_ms = _elapsed_ms(started_ns)
                elif line == "event: error":
                    return RequestResult(
                        response.status_code,
                        conversation_ms,
                        assistant_ms,
                        _elapsed_ms(started_ns),
                        "SSE error event",
                    )
        error = None
        if response.status_code != _HTTP_OK:
            error = f"HTTP {response.status_code}"
        elif conversation_ms is None or assistant_ms is None:
            error = "missing required SSE event"
        return RequestResult(
            response.status_code, conversation_ms, assistant_ms, _elapsed_ms(started_ns), error
        )
    except Exception as exc:
        return RequestResult(
            None,
            conversation_ms,
            assistant_ms,
            _elapsed_ms(started_ns),
            f"{type(exc).__name__}: {exc}",
        )


async def _probe_health(
    *, client: httpx.AsyncClient, base_url: str, done: asyncio.Event, interval_seconds: float
) -> tuple[list[float], int]:
    durations: list[float] = []
    errors = 0
    while True:
        started_ns = time.perf_counter_ns()
        try:
            response = await client.get(f"{base_url}/api/utils/health-check/")
            if response.status_code != _HTTP_OK:
                errors += 1
        except Exception:
            errors += 1
        durations.append(_elapsed_ms(started_ns))
        if done.is_set():
            break
        with suppress(TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=interval_seconds)
    return durations, errors


async def _run_level(
    *,
    client: httpx.AsyncClient,
    health_client: httpx.AsyncClient,
    base_url: str,
    concurrency: int,
    round_number: int,
    profile_count: int,
    health_interval_seconds: float,
) -> LevelResult:
    gate = asyncio.Event()
    ready = [asyncio.Event() for _ in range(concurrency)]
    tasks = [
        asyncio.create_task(
            _send_chat(
                client=client,
                base_url=base_url,
                gate=gate,
                ready=event,
                profile_index=(index * 137) % profile_count,
            )
        )
        for index, event in enumerate(ready)
    ]
    await asyncio.gather(*(event.wait() for event in ready))
    done = asyncio.Event()
    health_task = asyncio.create_task(
        _probe_health(
            client=health_client,
            base_url=base_url,
            done=done,
            interval_seconds=health_interval_seconds,
        )
    )
    started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    gate.set()
    results = await asyncio.gather(*tasks)
    cpu_ended_ns = time.process_time_ns()
    wall_ms = _elapsed_ms(started_ns)
    done.set()
    health_durations, health_errors = await health_task

    assistant = [result.assistant_ms for result in results if result.assistant_ms is not None]
    close = [result.close_ms for result in results]
    return LevelResult(
        concurrency=concurrency,
        round=round_number,
        errors=sum(result.error is not None for result in results),
        assistant_p50_ms=_percentile(assistant, 0.50) if assistant else None,
        assistant_p95_ms=_percentile(assistant, 0.95) if assistant else None,
        assistant_p99_ms=_percentile(assistant, 0.99) if assistant else None,
        close_p95_ms=_percentile(close, 0.95),
        wall_ms=wall_ms,
        client_cpu_percent=(cpu_ended_ns - cpu_started_ns) / (wall_ms * 1_000_000) * 100,
        health_samples=len(health_durations),
        health_errors=health_errors,
        health_p95_ms=_percentile(health_durations, 0.95),
        health_max_ms=max(health_durations),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.stress.chat_burst",
        description="Run synchronized authenticated SSE chats against an isolated stress DB.",
    )
    parser.add_argument("--version", action="version", version="chat-burst 0.1")
    parser.add_argument("--base-url", required=True, help="deployed API origin")
    parser.add_argument(
        "--concurrency", action="append", type=int, required=True, help="repeat for stepped levels"
    )
    parser.add_argument("--rounds", type=int, default=1, help="rounds per level; default: 1")
    parser.add_argument("--request-timeout-seconds", type=float, default=180, help="default: 180")
    parser.add_argument(
        "--health-interval-ms", type=float, default=100, help="health probe interval; default: 100"
    )
    parser.add_argument(
        "--allow-remote", action="store_true", help="required for non-localhost targets"
    )
    parser.add_argument(
        "--isolated-db-ack",
        action="store_true",
        help="acknowledge that the target writes only to a disposable database clone",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    base_url = _normalize_base_url(
        str(args.base_url),
        allow_remote=bool(args.allow_remote),
        isolated_db_ack=bool(args.isolated_db_ack),
    )
    if any(level <= 0 for level in args.concurrency) or args.rounds <= 0:
        raise RuntimeError("concurrency and rounds must be positive")
    token = os.environ.get("STRESS_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("STRESS_ACCESS_TOKEN is required")
    profiles_payload: object = json.loads(_PROFILE_PATH.read_text())
    if not isinstance(profiles_payload, list) or not profiles_payload:
        raise RuntimeError("stress profile fixture is empty")
    profiles = cast(list[object], profiles_payload)

    maximum = max(args.concurrency)
    limits = httpx.Limits(max_connections=maximum, max_keepalive_connections=maximum)
    timeout = httpx.Timeout(args.request_timeout_seconds)
    cookie_name = os.environ.get("STRESS_ACCESS_TOKEN_COOKIE_NAME", "va_access_token")
    output: list[LevelResult] = []
    async with (
        httpx.AsyncClient(limits=limits, timeout=timeout, cookies={cookie_name: token}) as client,
        httpx.AsyncClient(timeout=10) as health_client,
    ):
        health = await health_client.get(f"{base_url}/api/utils/health-check/")
        health.raise_for_status()
        for concurrency in args.concurrency:
            for round_number in range(1, args.rounds + 1):
                result = await _run_level(
                    client=client,
                    health_client=health_client,
                    base_url=base_url.rstrip("/"),
                    concurrency=concurrency,
                    round_number=round_number,
                    profile_count=len(profiles),
                    health_interval_seconds=args.health_interval_ms / 1000,
                )
                output.append(result)
                if not args.json:
                    print(json.dumps(asdict(result), separators=(",", ":")), flush=True)
    if args.json:
        print(json.dumps({"schema_version": 1, "levels": [asdict(item) for item in output]}))
    return 1 if any(item.errors or item.health_errors for item in output) else 0


def main() -> None:
    args = _build_parser().parse_args()
    try:
        exit_code = asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        exit_code = 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
