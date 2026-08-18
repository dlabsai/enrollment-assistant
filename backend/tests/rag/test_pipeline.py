from __future__ import annotations

import pytest

from app.rag import pipeline


@pytest.mark.asyncio
async def test_pipeline_ingests_demo_corpus_before_build(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    progress_statuses: list[dict[str, str]] = []

    class FakeLock:
        async def release(self) -> None:
            events.append("release")

    class FakeDemoStats:
        total_documents = 12

    async def fake_try_acquire_rag_pipeline_lock(*, job_name: str) -> FakeLock:
        assert job_name == "test"
        return FakeLock()

    async def fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
        del args, kwargs
        if func is pipeline.write_demo_rag_data:
            events.append("write_demo_rag_data")
            return FakeDemoStats()
        events.append(getattr(func, "__name__", "unknown"))
        return None

    async def fake_build_search_db(*_: object, **__: object) -> None:
        events.append("build_search_db")

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    vacuum_statements: list[str] = []

    class FakeConnection:
        async def execute(self, statement: object) -> None:
            vacuum_statements.append(str(statement))
            events.append("vacuum")

    class FakeConnectionContext:
        async def __aenter__(self) -> FakeConnection:
            return FakeConnection()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEngine:
        def execution_options(self, **_: object) -> FakeEngine:
            return self

        def connect(self) -> FakeConnectionContext:
            return FakeConnectionContext()

    async def progress_callback(snapshot: pipeline.RagPipelineProgressSnapshot) -> None:
        progress_statuses.append({step.key: step.status for step in snapshot.steps})

    def fake_get_session() -> FakeSessionContext:
        return FakeSessionContext()

    def fake_get_azure_openai_client() -> object:
        return object()

    async def fake_create_rag_build_job(**_: object) -> str:
        events.append("create_job")
        return "job-id"

    async def fake_start_rag_build_job(*_: object) -> None:
        events.append("start_job")

    async def fake_record_rag_build_progress(*_: object, **__: object) -> None:
        events.append("record_progress")

    async def fake_record_rag_build_source_stats(*_: object, **__: object) -> None:
        events.append("record_stats")

    async def fake_finish_rag_build_job(*_: object, **__: object) -> None:
        events.append("finish_job")

    async def fake_rag_build_cancellation_requested(*_: object) -> bool:
        return False

    monkeypatch.setattr(
        pipeline, "try_acquire_rag_pipeline_lock", fake_try_acquire_rag_pipeline_lock
    )
    monkeypatch.setattr(pipeline.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(pipeline, "get_session", fake_get_session)
    monkeypatch.setattr(pipeline, "get_azure_openai_client", fake_get_azure_openai_client)
    monkeypatch.setattr(pipeline, "build_search_db", fake_build_search_db)
    monkeypatch.setattr(pipeline, "create_rag_build_job", fake_create_rag_build_job)
    monkeypatch.setattr(pipeline, "start_rag_build_job", fake_start_rag_build_job)
    monkeypatch.setattr(pipeline, "record_rag_build_progress", fake_record_rag_build_progress)
    monkeypatch.setattr(
        pipeline, "record_rag_build_source_stats", fake_record_rag_build_source_stats
    )
    monkeypatch.setattr(pipeline, "finish_rag_build_job", fake_finish_rag_build_job)
    monkeypatch.setattr(
        pipeline, "rag_build_cancellation_requested", fake_rag_build_cancellation_requested
    )
    monkeypatch.setattr(pipeline, "engine", FakeEngine())

    await pipeline.run_rag_sync_pipeline(job_name="test", progress_callback=progress_callback)

    assert events.index("start_job") < events.index("write_demo_rag_data")
    assert events.index("write_demo_rag_data") < events.index("build_search_db")
    assert "release" in events
    assert vacuum_statements == [
        "VACUUM ANALYZE document",
        "VACUUM ANALYZE document_content_chunk",
        "VACUUM ANALYZE guardrail_url_registry",
    ]
    assert any(statuses["demo_corpus_ingest"] == "completed" for statuses in progress_statuses)


@pytest.mark.asyncio
async def test_pipeline_stops_between_steps_when_cancellation_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    finish_statuses: list[str] = []

    class FakeLock:
        async def release(self) -> None:
            events.append("release")

    class FakeDemoStats:
        total_documents = 12

    async def fake_try_acquire_rag_pipeline_lock(*, job_name: str) -> FakeLock:
        assert job_name == "test"
        return FakeLock()

    async def fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
        del args, kwargs
        events.append(getattr(func, "__name__", "unknown"))
        return FakeDemoStats()

    async def fake_create_rag_build_job(**_: object) -> str:
        return "job-id"

    async def fake_start_rag_build_job(*_: object) -> None:
        events.append("start_job")

    async def fake_record_rag_build_progress(*_: object, **__: object) -> None:
        return None

    async def fake_build_search_db(*_: object, **__: object) -> None:
        raise AssertionError("build_search_db should not run after cancellation")

    async def fake_finish_rag_build_job(*_: object, status: str, **__: object) -> None:
        finish_statuses.append(status)

    async def fake_rag_build_cancellation_requested(*_: object) -> bool:
        return "write_demo_rag_data" in events

    monkeypatch.setattr(
        pipeline, "try_acquire_rag_pipeline_lock", fake_try_acquire_rag_pipeline_lock
    )
    monkeypatch.setattr(pipeline.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(pipeline, "build_search_db", fake_build_search_db)
    monkeypatch.setattr(pipeline, "create_rag_build_job", fake_create_rag_build_job)
    monkeypatch.setattr(pipeline, "start_rag_build_job", fake_start_rag_build_job)
    monkeypatch.setattr(pipeline, "record_rag_build_progress", fake_record_rag_build_progress)
    monkeypatch.setattr(pipeline, "finish_rag_build_job", fake_finish_rag_build_job)
    monkeypatch.setattr(
        pipeline, "rag_build_cancellation_requested", fake_rag_build_cancellation_requested
    )

    with pytest.raises(pipeline.RagPipelineCancellationRequestedError):
        await pipeline.run_rag_sync_pipeline(job_name="test")

    assert "start_job" in events
    assert "write_demo_rag_data" in events
    assert "release" in events
    assert finish_statuses == ["cancelled"]


@pytest.mark.asyncio
async def test_pipeline_does_not_mark_lock_loser_running(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def fake_create_rag_build_job(**_: object) -> str:
        events.append("create")
        return "job-id"

    async def fake_try_acquire_rag_pipeline_lock(*, job_name: str) -> None:
        assert job_name == "test"
        events.append("try_lock")

    async def fail_start_rag_build_job(*_: object) -> None:
        raise AssertionError("A lock loser must not become running")

    async def fake_finish_rag_build_job(*_: object, status: str, **__: object) -> None:
        events.append(f"finish:{status}")

    async def fail_job_started_callback(*_: object) -> None:
        raise AssertionError("A lock loser must not be exposed as active")

    monkeypatch.setattr(pipeline, "create_rag_build_job", fake_create_rag_build_job)
    monkeypatch.setattr(
        pipeline, "try_acquire_rag_pipeline_lock", fake_try_acquire_rag_pipeline_lock
    )
    monkeypatch.setattr(pipeline, "start_rag_build_job", fail_start_rag_build_job)
    monkeypatch.setattr(pipeline, "finish_rag_build_job", fake_finish_rag_build_job)

    with pytest.raises(pipeline.RagPipelineAlreadyRunningError):
        await pipeline.run_rag_sync_pipeline(
            job_name="test", job_started_callback=fail_job_started_callback
        )

    assert events == ["create", "try_lock", "finish:skipped"]
