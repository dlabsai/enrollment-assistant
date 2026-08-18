import pytest

from app import main


@pytest.mark.asyncio
async def test_lifespan_closes_embedding_and_provider_clients_when_scheduler_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_close_embedding_client() -> None:
        events.append("close_embedding")

    async def fake_close_provider_http_clients() -> None:
        events.append("close_providers")

    async def fake_close_database_pools() -> None:
        events.append("close_database")

    async def fake_close_telemetry_database_pool() -> None:
        events.append("close_telemetry")

    monkeypatch.setattr(main.settings, "SCHEDULER", False)
    monkeypatch.setattr(main, "close_embedding_client", fake_close_embedding_client)
    monkeypatch.setattr(main, "close_provider_http_clients", fake_close_provider_http_clients)
    monkeypatch.setattr(main, "close_database_pools", fake_close_database_pools)
    monkeypatch.setattr(main, "close_telemetry_database_pool", fake_close_telemetry_database_pool)

    async with main.lifespan(main.app):
        events.append("running")

    assert events == [
        "running",
        "close_embedding",
        "close_providers",
        "close_database",
        "close_telemetry",
    ]
