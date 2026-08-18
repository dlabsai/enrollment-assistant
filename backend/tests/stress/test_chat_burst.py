from __future__ import annotations

import pytest

from app.stress.chat_burst import _normalize_base_url  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("acknowledgements", [(False, False), (True, False), (False, True)])
def test_chat_burst_requires_both_remote_safety_acknowledgements(
    acknowledgements: tuple[bool, bool],
) -> None:
    allow_remote, isolated_db_ack = acknowledgements
    with pytest.raises(RuntimeError, match="--allow-remote and --isolated-db-ack"):
        _normalize_base_url(
            "https://example.com", allow_remote=allow_remote, isolated_db_ack=isolated_db_ack
        )

    assert (
        _normalize_base_url("https://example.com/", allow_remote=True, isolated_db_ack=True)
        == "https://example.com"
    )


def test_chat_burst_accepts_local_target_without_acknowledgements() -> None:
    assert (
        _normalize_base_url("http://localhost:8000/", allow_remote=False, isolated_db_ack=False)
        == "http://localhost:8000"
    )
