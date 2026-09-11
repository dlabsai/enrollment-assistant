from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.orm import aliased

from app.core.rbac import PermissionKey
from app.models import (
    ComplianceFinding,
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    Conversation,
    Message,
    User,
)

from .failures import RETRIABLE_ERROR_CODES, admission_error_message, error_message
from .schemas import (
    FlagSummary,
    InstructionsDetail,
    ReviewState,
    ScreeningFailure,
    ScreeningSummary,
)
from .sources import visible_items

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


async def instructions_detail(
    session: AsyncSession, version: ComplianceInstructionsVersion
) -> InstructionsDetail:
    author = await session.scalar(select(User.name).where(User.id == version.created_by_id))
    return InstructionsDetail(
        id=version.id,
        number=version.number,
        created_at=version.created_at,
        author=author or "Former user",
        content=version.content,
    )


async def current_instructions(session: AsyncSession) -> ComplianceInstructionsVersion | None:
    return await session.scalar(
        select(ComplianceInstructionsVersion)
        .order_by(ComplianceInstructionsVersion.number.desc())
        .limit(1)
    )


type ScreeningRow = tuple[
    ComplianceScreening,
    str,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
]
type FlagRow = tuple[ComplianceItem, ComplianceFinding, str | None, UUID, UUID, datetime]
type FailureRow = tuple[UUID | None, str | None, str | None, int]


def screening_rows(
    user: User, permissions: Mapping[PermissionKey, bool], screening_id: UUID | None = None
) -> Select[ScreeningRow]:
    eligible = visible_items(user, permissions)
    if screening_id is not None:
        eligible = eligible.where(ComplianceItem.screening_id == screening_id)
    visible = eligible.with_only_columns(
        ComplianceItem.id,
        ComplianceItem.screening_id,
        ComplianceItem.conversation_id,
        ComplianceItem.status,
    ).cte("visible_compliance_items")
    stats = (
        select(
            visible.c.screening_id,
            func.count().label("messages"),
            func.count().filter(visible.c.status == "screened").label("screened"),
            func.count().filter(visible.c.status.in_(["queued", "running"])).label("pending"),
            func.count().filter(visible.c.status == "error").label("errors"),
            func.count().filter(visible.c.status == "deleted").label("deleted"),
        )
        .group_by(visible.c.screening_id)
        .subquery()
    )
    conversation_states = (
        select(
            visible.c.screening_id,
            visible.c.conversation_id,
            func.count().label("messages"),
            func.count().filter(visible.c.status == "screened").label("screened"),
            func.count().filter(visible.c.status == "error").label("errors"),
        )
        .where(visible.c.conversation_id.is_not(None))
        .group_by(visible.c.screening_id, visible.c.conversation_id)
        .subquery()
    )
    conversation_stats = (
        select(
            conversation_states.c.screening_id,
            func.count().label("conversations"),
            func.count()
            .filter(conversation_states.c.screened == conversation_states.c.messages)
            .label("screened_conversations"),
            func.count().filter(conversation_states.c.errors > 0).label("error_conversations"),
        )
        .group_by(conversation_states.c.screening_id)
        .subquery()
    )
    findings = (
        select(
            visible.c.screening_id,
            func.count(ComplianceFinding.id).label("findings"),
            func.count(ComplianceFinding.id)
            .filter(ComplianceFinding.review_state == "needs_review")
            .label("needs_review"),
        )
        .join(ComplianceFinding, ComplianceFinding.item_id == visible.c.id)
        .group_by(visible.c.screening_id)
        .subquery()
    )
    author = aliased(User)
    return (
        select(
            ComplianceScreening,
            author.name,
            stats.c.messages,
            conversation_stats.c.conversations,
            stats.c.screened,
            conversation_stats.c.screened_conversations,
            stats.c.pending,
            stats.c.errors,
            conversation_stats.c.error_conversations,
            stats.c.deleted,
            findings.c.findings,
            findings.c.needs_review,
        )
        .outerjoin(author, author.id == ComplianceScreening.created_by_id)
        .outerjoin(stats, stats.c.screening_id == ComplianceScreening.id)
        .outerjoin(conversation_stats, conversation_stats.c.screening_id == ComplianceScreening.id)
        .outerjoin(findings, findings.c.screening_id == ComplianceScreening.id)
        .where(
            or_(
                stats.c.messages > 0,
                ComplianceScreening.created_by_id == user.id,
                and_(
                    literal(permissions.get(PermissionKey.ACCESS_COMPLIANCE, False)),
                    ComplianceScreening.admission_error_code.is_not(None),
                ),
            )
        )
    )


async def summaries(
    session: AsyncSession, statement: Select[ScreeningRow]
) -> list[ScreeningSummary]:
    return [
        ScreeningSummary(
            id=screening.id,
            created_at=screening.created_at,
            author=author or "Former user",
            start=screening.start_at,
            end=screening.end_at,
            instructions_version_id=screening.instructions_version_id,
            admission_error=admission_error_message(screening.admission_error_code),
            messages=messages or 0,
            conversations=conversations or 0,
            screened=screened or 0,
            screened_conversations=screened_conversations or 0,
            pending=pending or 0,
            errors=errors or 0,
            error_conversations=error_conversations or 0,
            deleted=deleted or 0,
            findings=findings or 0,
            needs_review=needs_review or 0,
        )
        for (
            screening,
            author,
            messages,
            conversations,
            screened,
            screened_conversations,
            pending,
            errors,
            error_conversations,
            deleted,
            findings,
            needs_review,
        ) in (await session.execute(statement)).all()
    ]


async def require_screening(
    session: AsyncSession, user: User, permissions: Mapping[PermissionKey, bool], screening_id: UUID
) -> ScreeningSummary:
    rows = await summaries(
        session,
        screening_rows(user, permissions, screening_id).where(
            ComplianceScreening.id == screening_id
        ),
    )
    if not rows:
        raise HTTPException(404, "This screening is unavailable or outside your chat access.")
    return rows[0]


def failure_rows(
    user: User, permissions: Mapping[PermissionKey, bool], screening_id: UUID
) -> Select[FailureRow]:
    return (
        visible_items(user, permissions)
        .where(
            ComplianceItem.screening_id == screening_id,
            ComplianceItem.status == "error",
            ComplianceItem.conversation_id.is_not(None),
        )
        .with_only_columns(
            ComplianceItem.conversation_id,
            Conversation.title,
            ComplianceItem.error_code,
            func.count(),
        )
        .group_by(ComplianceItem.conversation_id, Conversation.title, ComplianceItem.error_code)
    )


async def failure_summaries(
    session: AsyncSession, statement: Select[FailureRow], *, retry_supported: bool
) -> list[ScreeningFailure]:
    failures: list[ScreeningFailure] = []
    for chat_id, title, code, messages in (await session.execute(statement)).all():
        if chat_id is None:
            continue
        retryable = code in RETRIABLE_ERROR_CODES
        reason = error_message(code or "")
        if retryable and not retry_supported:
            reason = f"{reason} {error_message('screening_version_changed')}"
        failures.append(
            ScreeningFailure(
                chat_id=chat_id,
                chat=title or "Untitled chat",
                assistant_messages=messages,
                reason=reason,
                retryable=retryable and retry_supported,
            )
        )
    return failures


def flag_rows(
    user: User, permissions: Mapping[PermissionKey, bool], screening_id: UUID
) -> Select[FlagRow]:
    return (
        visible_items(user, permissions)
        .where(ComplianceItem.screening_id == screening_id)
        .join(ComplianceFinding, ComplianceFinding.item_id == ComplianceItem.id)
        .join(Message, Message.id == ComplianceFinding.message_id)
        .add_columns(
            ComplianceFinding,
            Conversation.title,
            Message.id,
            Message.conversation_id,
            Message.created_at,
        )
    )


async def flag_summaries(session: AsyncSession, statement: Select[FlagRow]) -> list[FlagSummary]:
    return [
        FlagSummary(
            id=finding.id,
            title=finding.title,
            chat=title or "Untitled chat",
            message_at=message_at,
            state=ReviewState(finding.review_state),
        )
        for _item, finding, title, _message_id, _conversation_id, message_at in (
            await session.execute(statement)
        ).all()
    ]
