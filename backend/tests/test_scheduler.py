from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from app import scheduler as scheduler_module
from app import scheduler_runner

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.mark.asyncio
async def test_sync_data_job_skips_pipeline_when_scheduler_lock_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_calls: list[tuple[int, str]] = []

    @asynccontextmanager
    async def fake_job_lock(lock_id: int, *, job_name: str) -> AsyncGenerator[bool]:
        lock_calls.append((lock_id, job_name))
        yield False

    async def fail_run_rag_sync_pipeline(**_: Any) -> None:
        raise AssertionError("RAG pipeline should not run without the scheduler lock")

    monkeypatch.setattr(scheduler_module, "_job_lock", fake_job_lock)
    monkeypatch.setattr(scheduler_module, "run_rag_sync_pipeline", fail_run_rag_sync_pipeline)

    await scheduler_module.sync_data_job()

    assert len(lock_calls) == 1
    lock_id, job_name = lock_calls[0]
    assert isinstance(lock_id, int)
    assert job_name == "sync_data_job"


@pytest.mark.asyncio
async def test_sync_data_job_runs_scheduled_pipeline_when_scheduler_lock_is_acquired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def fake_job_lock(_lock_id: int, *, job_name: str) -> AsyncGenerator[bool]:
        assert job_name == "sync_data_job"
        yield True

    async def fake_run_rag_sync_pipeline(**kwargs: object) -> None:
        pipeline_calls.append(dict(kwargs))

    monkeypatch.setattr(scheduler_module, "_job_lock", fake_job_lock)
    monkeypatch.setattr(scheduler_module, "run_rag_sync_pipeline", fake_run_rag_sync_pipeline)

    await scheduler_module.sync_data_job()

    assert pipeline_calls == [{"job_name": "sync_data_job", "job_trigger": "scheduled"}]


@pytest.mark.asyncio
async def test_scheduler_runner_exits_without_starting_scheduler_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeScheduler:
        def start(self) -> None:
            events.append("start")

        def shutdown(self) -> None:
            events.append("shutdown")

    async def fail_wait_for_shutdown() -> None:
        raise AssertionError("scheduler runner should not wait when SCHEDULER=false")

    monkeypatch.setattr(scheduler_runner.settings, "SCHEDULER", False)
    monkeypatch.setattr(scheduler_runner, "configure_observability", lambda: events.append("obs"))
    monkeypatch.setattr(
        scheduler_runner, "configure_otel_span_processor", lambda: events.append("otel")
    )
    monkeypatch.setattr(
        scheduler_runner, "configure_scheduler_jobs", lambda: events.append("configure")
    )
    monkeypatch.setattr(scheduler_runner, "scheduler", FakeScheduler())
    monkeypatch.setattr(scheduler_runner, "_wait_for_shutdown", fail_wait_for_shutdown)

    await scheduler_runner.main()

    assert events == ["obs", "otel"]


@pytest.mark.asyncio
async def test_scheduler_runner_starts_and_stops_scheduler_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeScheduler:
        def start(self) -> None:
            events.append("start")

        def shutdown(self) -> None:
            events.append("shutdown")

    async def fake_wait_for_shutdown() -> None:
        events.append("wait")

    monkeypatch.setattr(scheduler_runner.settings, "SCHEDULER", True)
    monkeypatch.setattr(scheduler_runner, "configure_observability", lambda: events.append("obs"))
    monkeypatch.setattr(
        scheduler_runner, "configure_otel_span_processor", lambda: events.append("otel")
    )
    monkeypatch.setattr(
        scheduler_runner, "configure_scheduler_jobs", lambda: events.append("configure")
    )
    monkeypatch.setattr(scheduler_runner, "scheduler", FakeScheduler())
    monkeypatch.setattr(scheduler_runner, "_wait_for_shutdown", fake_wait_for_shutdown)

    await scheduler_runner.main()

    assert events == ["obs", "otel", "configure", "start", "wait", "shutdown"]
