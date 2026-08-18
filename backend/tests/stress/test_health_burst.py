from __future__ import annotations

import httpx
import pytest

from app.stress import health_burst


def _config(**overrides: object) -> health_burst.RunConfig:
    values: dict[str, object] = {
        "base_url": "http://localhost:8000",
        "path": "/api/utils/health-check/",
        "concurrency": (1, 3),
        "rounds": 2,
        "warmup_rounds": 0,
        "request_timeout_seconds": 1.0,
        "settle_seconds": 0.0,
        "round_pause_seconds": 0.0,
        "process_matches": (),
        "process_sample_interval_seconds": 0.01,
    }
    values.update(overrides)
    return health_burst.RunConfig(**values)  # pyright: ignore[reportArgumentType]


def test_elapsed_ms_rejects_negative_monotonic_duration() -> None:
    with pytest.raises(health_burst.ClockInvariantError, match="moved backwards"):
        health_burst._elapsed_ms(20, 19)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_remote_target_requires_explicit_acknowledgement() -> None:
    with pytest.raises(health_burst.CliError, match="--allow-remote"):
        health_burst._normalize_base_url(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            "https://example.com", allow_remote=False
        )

    assert (
        health_burst._normalize_base_url(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            "https://example.com/", allow_remote=True
        )
        == "https://example.com"
    )


@pytest.mark.asyncio
async def test_health_burst_uses_all_concurrency_levels_and_rounds() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/utils/health-check/"
        return httpx.Response(200, json=True)

    config = _config()
    rounds = await health_burst.run_health_burst(config, transport=httpx.MockTransport(handler))
    summaries = health_burst.summarize_run(config.concurrency, rounds)

    assert len(rounds) == 4
    assert [summary.concurrency for summary in summaries] == [1, 3]
    assert [summary.requests for summary in summaries] == [2, 6]
    assert all(summary.errors == 0 for summary in summaries)
    assert all(request.elapsed_ms >= 0 for result in rounds for request in result.requests)


@pytest.mark.asyncio
async def test_health_burst_reports_bad_health_payload_as_failure() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True}))
    config = _config(concurrency=(2,), rounds=1)

    rounds = await health_burst.run_health_burst(config, transport=transport)
    summary = health_burst.summarize_run(config.concurrency, rounds)[0]

    assert summary.errors == 2
    assert {request.error for request in rounds[0].requests} == {
        "health response body was not JSON true"
    }
