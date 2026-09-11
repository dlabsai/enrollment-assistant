# pyright: reportPrivateUsage=false

from uuid import uuid4

import pytest

from app.api.routes import conversations as conversation_routes
from app.api.routes.conversations import (  # pyright: ignore[reportPrivateUsage]
    _cap_chat_export_ids,
    _chat_export_information_rows,
)


def test_chat_export_caps_ids_without_rejecting_request(monkeypatch: pytest.MonkeyPatch) -> None:
    conversation_ids = [uuid4(), uuid4(), uuid4()]
    monkeypatch.setattr(conversation_routes, "_CHAT_EXPORT_MAX_CONVERSATIONS", 2)

    selected_ids, truncated = _cap_chat_export_ids(conversation_ids)

    assert selected_ids == conversation_ids[:2]
    assert truncated is True


def test_chat_export_information_records_omitted_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation_routes, "_CHAT_EXPORT_MAX_CONVERSATIONS", 2)

    rows = dict(_chat_export_information_rows(included_count=2, truncated=True))

    assert rows == {
        "Chats included": 2,
        "Export limit": 2,
        "Additional matching chats omitted": "Yes",
        "Notice": (
            "The selected filters matched more chats than the export limit of 2. "
            "This export contains 2 chats. Additional matching chats were not included."
        ),
    }
