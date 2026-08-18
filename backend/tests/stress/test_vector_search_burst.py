from __future__ import annotations

import pytest

from app.stress.vector_search_burst import (
    _QUERY,  # pyright: ignore[reportPrivateUsage]
    _connection_kwargs,  # pyright: ignore[reportPrivateUsage]
    _percentile,  # pyright: ignore[reportPrivateUsage]
)


def test_percentile_uses_nearest_rank() -> None:
    values = [50.0, 10.0, 40.0, 20.0, 30.0]

    assert _percentile(values, 0.5) == 30.0
    assert _percentile(values, 0.95) == 50.0


def test_connection_kwargs_enforce_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "PGHOST": "database.example.invalid",
        "PGPORT": "5432",
        "PGDATABASE": "app",
        "PGUSER": "readonly_user",
        "PGPASSWORD": "secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    kwargs = _connection_kwargs(60, 120)

    assert kwargs["autocommit"] is True
    assert kwargs["connect_timeout"] == 120
    assert "default_transaction_read_only=on" in kwargs["options"]
    assert "statement_timeout=60000" in kwargs["options"]


def test_capacity_query_is_select_only_and_avoids_chunk_body_transfer() -> None:
    normalized = " ".join(_QUERY.lower().split())

    assert normalized.startswith("select ")
    assert "c.content," not in normalized
    assert "order by c.content_embedding <-> %s::vector" in normalized
    assert normalized.endswith("limit 150")
