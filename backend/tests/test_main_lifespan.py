import asyncio

import pytest

from app import main


@pytest.mark.asyncio
async def test_lifespan_stops_worker_before_provider_and_database_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_worker() -> None:
        events.append("worker_started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("worker_stopped")

    def fake_start_worker() -> asyncio.Task[None]:
        return asyncio.create_task(fake_worker())

    async def fake_close_embedding_client() -> None:
        events.append("close_embedding")

    async def fake_close_provider_http_clients() -> None:
        events.append("close_providers")

    async def fake_close_database_pools() -> None:
        events.append("close_database")

    async def fake_close_telemetry_database_pool() -> None:
        events.append("close_telemetry")

    monkeypatch.setattr(main.settings, "SCHEDULER", False)
    monkeypatch.setattr(main, "start_worker", fake_start_worker)
    monkeypatch.setattr(main, "close_embedding_client", fake_close_embedding_client)
    monkeypatch.setattr(main, "close_provider_http_clients", fake_close_provider_http_clients)
    monkeypatch.setattr(main, "close_database_pools", fake_close_database_pools)
    monkeypatch.setattr(main, "close_telemetry_database_pool", fake_close_telemetry_database_pool)

    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        events.append("running")

    assert events == [
        "worker_started",
        "running",
        "worker_stopped",
        "close_embedding",
        "close_providers",
        "close_database",
        "close_telemetry",
    ]
