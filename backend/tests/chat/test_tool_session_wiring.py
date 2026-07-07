from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from app.chat.tools.deps import Deps
from app.chat.tools.website import list_website_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class _FakeResult:
    def all(self) -> list[object]:
        row = MagicMock()
        row.id_ = 123
        row.title = "Admissions"
        return [row]


class _FakeSession:
    def __init__(self) -> None:
        self.execute_calls = 0

    async def execute(self, _stmt: object) -> _FakeResult:
        self.execute_calls += 1
        return _FakeResult()


@pytest.mark.asyncio
async def test_chat_tools_use_a_fresh_session_from_deps_factory() -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def session_factory() -> AsyncGenerator[_FakeSession]:
        yield session

    deps = Deps(openai=MagicMock(), session_factory=session_factory)  # pyright: ignore[reportArgumentType]
    ctx = MagicMock()
    ctx.deps = deps

    pages = await list_website_pages(ctx)

    assert pages == [(123, "Admissions")]
    assert session.execute_calls == 1
