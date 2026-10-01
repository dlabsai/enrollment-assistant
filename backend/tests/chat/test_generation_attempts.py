from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from app import scheduler as scheduler_module
from app.chat.generation_attempts import (
    STALE_GENERATION_ATTEMPT_AFTER,
    fail_stale_generation_attempts,
)
from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.models import ChatGenerationAttempt, Conversation, User
from app.utils import current_time_utc

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession


async def _create_attempts(
    session: AsyncSession, statuses_and_ages: list[tuple[str, timedelta]]
) -> list[ChatGenerationAttempt]:
    group = await get_group_for_slug(session, SystemGroupSlug.USER)
    user = User(
        email=f"attempts-{uuid4()}@example.com",
        name="Attempt Owner",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.flush()
    conversation = Conversation(
        title="Attempts", user=False, project="demo", user_id=user.id, is_public=False
    )
    session.add(conversation)
    await session.flush()
    attempts = [
        ChatGenerationAttempt(
            user_id=user.id,
            conversation_id=conversation.id,
            request_fingerprint="a" * 64,
            status=status,
            created_at=current_time_utc() - age,
        )
        for status, age in statuses_and_ages
    ]
    session.add_all(attempts)
    await session.commit()
    return attempts


async def _statuses(session: AsyncSession, attempts: list[ChatGenerationAttempt]) -> list[str]:
    for attempt in attempts:
        await session.refresh(attempt)
    return [attempt.status for attempt in attempts]


@pytest.mark.asyncio
async def test_fail_stale_generation_attempts_only_fails_old_pending_attempts(
    transactional_session: AsyncSession,
) -> None:
    stale = STALE_GENERATION_ATTEMPT_AFTER + timedelta(minutes=1)
    fresh = STALE_GENERATION_ATTEMPT_AFTER - timedelta(minutes=1)
    attempts = await _create_attempts(
        transactional_session,
        [("pending", stale), ("pending", fresh), ("completed", stale), ("failed", stale)],
    )

    failed_count = await fail_stale_generation_attempts(transactional_session)

    assert failed_count == 1
    assert await _statuses(transactional_session, attempts) == [
        "failed",
        "pending",
        "completed",
        "failed",
    ]
    assert await fail_stale_generation_attempts(transactional_session) == 0


@pytest.mark.asyncio
async def test_stale_generation_attempt_job_fails_abandoned_attempts(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = await _create_attempts(
        transactional_session, [("pending", STALE_GENERATION_ATTEMPT_AFTER + timedelta(hours=1))]
    )

    @asynccontextmanager
    async def use_test_session() -> AsyncGenerator[AsyncSession]:
        yield transactional_session

    monkeypatch.setattr(scheduler_module, "get_session", use_test_session)

    await scheduler_module.fail_stale_generation_attempts_job()

    assert await _statuses(transactional_session, attempts) == ["failed"]
