from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from app.compliance import scheduled
from app.compliance.queries import require_screening
from app.compliance.scheduled import SCHEDULER_USER_EMAIL
from app.core.rbac import SystemGroupSlug, get_effective_permission_map
from app.models import (
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    RbacUserPermissionOverride,
    User,
)
from tests.api.compliance_helpers import make_chat, make_user

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def _existing_session(session: AsyncSession) -> AsyncGenerator[AsyncSession]:
    yield session


def test_previous_eastern_day_respects_daylight_saving_time() -> None:
    local_date, start, end = scheduled.previous_eastern_day(datetime(2026, 11, 2, 7, tzinfo=UTC))

    assert local_date == date(2026, 11, 1)
    assert start == datetime(2026, 11, 1, 4, tzinfo=UTC)
    assert end == datetime(2026, 11, 2, 4, 59, 59, 999999, tzinfo=UTC)


@pytest.mark.asyncio
async def test_daily_screening_skips_empty_work(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduled.settings, "COMPLIANCE_WORKER_ENABLED", True)
    monkeypatch.setattr(scheduled, "get_session", lambda: _existing_session(transactional_session))
    requester = await transactional_session.scalar(
        select(User).where(User.email == SCHEDULER_USER_EMAIL)
    )
    assert requester is not None
    now = datetime(2026, 9, 3, 6, 30, tzinfo=UTC)

    assert await scheduled.admit_daily_screening(now=now) is None

    transactional_session.add(
        ComplianceInstructionsVersion(
            number=1, content="Flag admission guarantees.", created_by_id=requester.id
        )
    )
    await transactional_session.flush()
    assert await scheduled.admit_daily_screening(now=now) is None
    assert (
        await transactional_session.scalar(select(func.count()).select_from(ComplianceScreening))
        == 0
    )


@pytest.mark.asyncio
async def test_daily_screening_persists_an_oversized_failure(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduled.settings, "COMPLIANCE_WORKER_ENABLED", True)
    monkeypatch.setattr(scheduled.settings, "COMPLIANCE_MAX_MESSAGES", 1)
    monkeypatch.setattr(scheduled, "get_session", lambda: _existing_session(transactional_session))
    requester = await transactional_session.scalar(
        select(User).where(User.email == SCHEDULER_USER_EMAIL)
    )
    assert requester is not None
    transactional_session.add(
        ComplianceInstructionsVersion(
            number=1, content="Flag admission guarantees.", created_by_id=requester.id
        )
    )
    reviewer = await make_user(transactional_session, SystemGroupSlug.DEV)
    staff = await make_user(transactional_session, SystemGroupSlug.USER)
    _, first = await make_chat(transactional_session, staff)
    _, second = await make_chat(transactional_session, staff)
    first.created_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    second.created_at = datetime(2026, 9, 1, 13, tzinfo=UTC)
    await transactional_session.flush()

    screening_id = await scheduled.admit_daily_screening(
        now=datetime(2026, 9, 2, 6, 30, tzinfo=UTC)
    )

    assert screening_id == scheduled.scheduled_screening_id(date(2026, 9, 1))
    assert screening_id is not None
    screening = await transactional_session.get(ComplianceScreening, screening_id)
    assert screening is not None
    assert (
        await transactional_session.scalar(
            select(func.count())
            .select_from(ComplianceItem)
            .where(ComplianceItem.screening_id == screening_id)
        )
        == 0
    )
    summary = await require_screening(
        transactional_session,
        reviewer,
        await get_effective_permission_map(transactional_session, reviewer),
        screening_id,
    )
    assert summary.admission_error == (
        "Too many assistant messages were eligible for this scheduled screening. "
        "Start separate manual screenings for shorter periods."
    )


@pytest.mark.asyncio
async def test_daily_screening_is_attributed_scoped_and_idempotent(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduled.settings, "COMPLIANCE_WORKER_ENABLED", True)
    monkeypatch.setattr(scheduled, "get_session", lambda: _existing_session(transactional_session))
    requester = await transactional_session.scalar(
        select(User).where(User.email == SCHEDULER_USER_EMAIL)
    )
    assert requester is not None
    assert requester.name == "Screening Scheduler"
    assert requester.is_active is True
    overrides = set(
        await transactional_session.scalars(
            select(RbacUserPermissionOverride.permission_key).where(
                RbacUserPermissionOverride.user_id == requester.id,
                RbacUserPermissionOverride.is_allowed.is_(True),
            )
        )
    )
    assert overrides == {"access_compliance", "chats_view_users", "chats_view_admins"}

    instructions = ComplianceInstructionsVersion(
        number=1, content="Flag admission guarantees.", created_by_id=requester.id
    )
    transactional_session.add(instructions)
    staff = await make_user(transactional_session, SystemGroupSlug.USER)
    admin = await make_user(transactional_session, SystemGroupSlug.ADMIN)
    _, staff_message = await make_chat(transactional_session, staff)
    _, admin_message = await make_chat(transactional_session, admin)
    _, current_day_message = await make_chat(transactional_session, staff)
    staff_message.created_at = datetime(2026, 9, 2, 12, tzinfo=UTC)
    admin_message.created_at = datetime(2026, 9, 3, 3, 59, 59, 999999, tzinfo=UTC)
    current_day_message.created_at = datetime(2026, 9, 3, 4, tzinfo=UTC)
    await transactional_session.flush()

    now = datetime(2026, 9, 3, 6, 30, tzinfo=UTC)
    first_id = await scheduled.admit_daily_screening(now=now)
    second_id = await scheduled.admit_daily_screening(now=now)

    assert first_id == second_id == scheduled.scheduled_screening_id(date(2026, 9, 2))
    screening = await transactional_session.get(ComplianceScreening, first_id)
    assert screening is not None
    assert screening.created_by_id == requester.id
    assert screening.instructions_version_id == instructions.id
    assert screening.created_at == now
    assert screening.start_at == datetime(2026, 9, 2, 4, tzinfo=UTC)
    assert screening.end_at == datetime(2026, 9, 3, 3, 59, 59, 999999, tzinfo=UTC)
    items = list(
        (
            await transactional_session.scalars(
                select(ComplianceItem).where(ComplianceItem.screening_id == screening.id)
            )
        ).all()
    )
    assert {item.message_id for item in items} == {staff_message.id, admin_message.id}
    assert {item.requested_by_id for item in items} == {requester.id}
    assert (
        await transactional_session.scalar(
            select(func.count())
            .select_from(ComplianceScreening)
            .where(ComplianceScreening.id == screening.id)
        )
        == 1
    )
