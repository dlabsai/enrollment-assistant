from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.rbac import PermissionKey, get_effective_permission_map
from app.models import (
    ComplianceFinding,
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    Conversation,
    User,
)
from app.utils import current_time_utc, logger

from .schemas import TranscriptMessage
from .screener import SCREENING_VERSION, ValidatedConcern, screen_conversation
from .sources import ScreeningUnavailableError, load_transcript, transcript_hash, visible_items

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession


type SessionFactory = Callable[[], AsyncSession]

LEASE_SECONDS = 90
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Claim:
    screening_id: UUID
    conversation_id: UUID
    token: UUID


@dataclass(frozen=True)
class Work:
    target_message_ids: tuple[UUID, ...]
    context_as_of: datetime
    instructions: str
    transcript: list[TranscriptMessage]
    input_hash: str
    model_name: str
    max_tokens: int
    max_input_characters: int


def _claim_condition(claim: Claim) -> ColumnElement[bool]:
    return and_(
        ComplianceItem.screening_id == claim.screening_id,
        ComplianceItem.conversation_id == claim.conversation_id,
        ComplianceItem.lease_token == claim.token,
        ComplianceItem.status == "running",
        ComplianceItem.message_id.is_not(None),
    )


async def claim_next(session: AsyncSession) -> Claim | None:
    now = current_time_utc()
    # Lock the conversation first so workers cannot split its targets into separate calls.
    selected = (
        await session.execute(
            select(Conversation.id, ComplianceItem.screening_id)
            .join(ComplianceItem, ComplianceItem.conversation_id == Conversation.id)
            .where(
                ComplianceItem.message_id.is_not(None),
                or_(
                    ComplianceItem.status == "queued",
                    and_(ComplianceItem.status == "running", ComplianceItem.leased_until < now),
                ),
            )
            .order_by(ComplianceItem.created_at, ComplianceItem.id)
            .limit(1)
            .with_for_update(of=Conversation, skip_locked=True)
        )
    ).first()
    if selected is None:
        return None
    conversation_id, screening_id = selected
    items = list(
        (
            await session.scalars(
                select(ComplianceItem)
                .where(
                    ComplianceItem.screening_id == screening_id,
                    ComplianceItem.conversation_id == conversation_id,
                    ComplianceItem.status.in_(["queued", "running"]),
                    ComplianceItem.message_id.is_not(None),
                )
                .order_by(ComplianceItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if not items or any(
        item.status == "running" and item.leased_until is not None and item.leased_until >= now
        for item in items
    ):
        return None
    exhausted = any(item.attempts >= MAX_ATTEMPTS for item in items)
    token = uuid4()
    for item in items:
        if exhausted:
            item.status = "error"
            item.error_code = "worker_interrupted"
            item.lease_token = None
            item.leased_until = None
        else:
            item.status = "running"
            item.attempts += 1
            item.lease_token = token
            item.leased_until = now + timedelta(seconds=LEASE_SECONDS)
    return None if exhausted else Claim(screening_id, conversation_id, token)


async def authorized_items(
    session: AsyncSession, claim: Claim, items: Sequence[ComplianceItem]
) -> bool:
    requester_id = items[0].requested_by_id
    if requester_id is None or any(item.requested_by_id != requester_id for item in items):
        return False
    requester = await session.scalar(
        select(User).options(joinedload(User.group)).where(User.id == requester_id)
    )
    if requester is None or not requester.is_active:
        return False
    permissions = await get_effective_permission_map(session, requester)
    if not permissions.get(PermissionKey.ACCESS_COMPLIANCE):
        return False
    count = await session.scalar(
        visible_items(requester, permissions)
        .with_only_columns(func.count())
        .where(_claim_condition(claim))
    )
    return count == len(items)


async def prepare_work(session: AsyncSession, claim: Claim) -> Work | None:
    items = list(
        (await session.scalars(select(ComplianceItem).where(_claim_condition(claim)))).all()
    )
    if not items:
        return None
    if not await authorized_items(session, claim, items):
        raise ScreeningUnavailableError("access_changed")
    screening = await session.get(ComplianceScreening, claim.screening_id)
    if screening is None or screening.screening_version != SCREENING_VERSION:
        raise ScreeningUnavailableError("screening_version_changed")
    instructions = await session.get(
        ComplianceInstructionsVersion, screening.instructions_version_id
    )
    if instructions is None:
        raise ScreeningUnavailableError("screening_version_changed")
    transcript = await load_transcript(session, claim.conversation_id, as_of=screening.created_at)
    target_ids = {item.message_id for item in items if item.message_id is not None}
    expected_target_ids = {
        message.id
        for message in transcript
        if message.role == "assistant"
        and screening.start_at <= message.created_at <= screening.end_at
    }
    if target_ids != expected_target_ids:
        raise ScreeningUnavailableError("invalid_context")
    return Work(
        target_message_ids=tuple(message.id for message in transcript if message.id in target_ids),
        context_as_of=screening.created_at,
        instructions=instructions.content,
        transcript=transcript,
        input_hash=transcript_hash(transcript),
        model_name=screening.model_name,
        max_tokens=int(screening.model_settings["max_tokens"]),
        max_input_characters=int(screening.model_settings["max_input_characters"]),
    )


async def finish_error(session: AsyncSession, claim: Claim, code: str) -> None:
    await session.execute(
        update(ComplianceItem)
        .where(_claim_condition(claim))
        .values(status="error", error_code=code, lease_token=None, leased_until=None)
    )


async def finish_result(
    session: AsyncSession, claim: Claim, work: Work, concerns: list[ValidatedConcern]
) -> bool:
    # Match claim/deletion order: conversation, source messages, then compliance items.
    source = await session.scalar(
        select(Conversation.id).where(Conversation.id == claim.conversation_id).with_for_update()
    )
    if source is None:
        return False
    transcript = await load_transcript(
        session, claim.conversation_id, as_of=work.context_as_of, lock=True
    )
    items = list(
        (
            await session.scalars(
                select(ComplianceItem).where(_claim_condition(claim)).with_for_update()
            )
        ).all()
    )
    if not items:
        return False
    if not await authorized_items(session, claim, items):
        await finish_error(session, claim, "access_changed")
        return False
    by_message = {item.message_id: item for item in items if item.message_id is not None}
    if (
        set(by_message) != set(work.target_message_ids)
        or transcript_hash(transcript) != work.input_hash
    ):
        await finish_error(session, claim, "invalid_context")
        return False
    if any(concern.message_id not in by_message for concern in concerns):
        await finish_error(session, claim, "invalid_evidence")
        return False
    session.add_all(
        ComplianceFinding(
            item_id=by_message[concern.message_id].id,
            message_id=concern.message_id,
            title=concern.title,
            explanation=concern.explanation,
            evidence_start=concern.evidence_start,
            evidence_end=concern.evidence_end,
            instruction_start=concern.instruction_start,
            instruction_end=concern.instruction_end,
        )
        for concern in concerns
    )
    for item in items:
        item.status = "screened"
        item.input_hash = work.input_hash
        item.error_code = None
        item.lease_token = None
        item.leased_until = None
    return True


async def _heartbeat(
    factory: SessionFactory,
    claim: Claim,
    lost: asyncio.Event,
    screening_task: asyncio.Task[list[ValidatedConcern]],
) -> None:
    while True:
        await asyncio.sleep(20)
        try:
            async with factory() as session:
                result = await session.scalar(
                    update(ComplianceItem)
                    .where(_claim_condition(claim))
                    .values(leased_until=current_time_utc() + timedelta(seconds=LEASE_SECONDS))
                    .returning(ComplianceItem.id)
                )
                await session.commit()
            if result is not None:
                continue
        except Exception as exc:
            logger.warning("Compliance lease unavailable (%s)", type(exc).__name__)
        lost.set()
        screening_task.cancel()
        return


async def execute_claim(factory: SessionFactory, claim: Claim) -> None:
    try:
        async with factory() as session:
            work = await prepare_work(session, claim)
            await session.commit()
        if work is None:
            return
        lost = asyncio.Event()
        screening_task = asyncio.create_task(
            screen_conversation(
                instructions=work.instructions,
                transcript=work.transcript,
                target_message_ids=work.target_message_ids,
                model_name=work.model_name,
                max_tokens=work.max_tokens,
                max_input_characters=work.max_input_characters,
            )
        )
        heartbeat = asyncio.create_task(_heartbeat(factory, claim, lost, screening_task))
        try:
            concerns = await screening_task
        except asyncio.CancelledError:
            if lost.is_set():
                return
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        async with factory() as session:
            await finish_result(session, claim, work, concerns)
            await session.commit()
    except ScreeningUnavailableError as exc:
        code = exc.code
    except Exception:
        # Provider/validation exceptions can contain requests or model output.
        code = "provider_error"
    else:
        return
    async with factory() as session:
        await finish_error(session, claim, code)
        await session.commit()


async def run_worker() -> None:
    """Screen each claimed conversation's pending targets together."""
    while True:
        try:
            async with async_session_factory() as session:
                claim = await claim_next(session)
                await session.commit()
            if claim is not None:
                await execute_claim(async_session_factory, claim)
                continue
        except Exception as exc:
            logger.warning("Compliance queue unavailable (%s)", type(exc).__name__)
        await asyncio.sleep(5)


def start_worker() -> asyncio.Task[None] | None:
    return (
        asyncio.create_task(run_worker(), name="compliance-worker")
        if settings.COMPLIANCE_WORKER_ENABLED
        else None
    )
