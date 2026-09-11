from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID  # noqa: TC003 - FastAPI resolves runtime annotations.

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, or_, select, text, update

from app.api.deps import CurrentUser, SessionDep
from app.compliance.admission import (
    NoEligibleMessagesError,
    ScreeningTooLargeError,
    admit_screening,
)
from app.compliance.failures import RETRIABLE_ERROR_CODES, error_message
from app.compliance.queries import (
    current_instructions,
    failure_rows,
    failure_summaries,
    flag_rows,
    flag_summaries,
    instructions_detail,
    require_screening,
    screening_rows,
    summaries,
)
from app.compliance.schemas import (
    DecisionInput,
    DecisionOut,
    DecisionState,
    FindingOut,
    FlagDetail,
    FlagsPage,
    InstructionsDetail,
    InstructionsPage,
    InstructionsSummary,
    Overlap,
    Preview,
    ReviewState,
    SaveInstructions,
    ScreeningDetail,
    ScreeningPeriod,
    ScreeningsPage,
    StartScreening,
)
from app.compliance.screener import SCREENING_VERSION
from app.compliance.sources import (
    ScreeningUnavailableError,
    load_transcript,
    source_selection,
    transcript_hash,
    visible_items,
)
from app.core.config import settings
from app.core.rbac import PermissionKey, get_effective_permission_map
from app.models import (
    ComplianceDecision,
    ComplianceFinding,
    ComplianceInstructionsVersion,
    ComplianceItem,
    ComplianceScreening,
    Conversation,
    Message,
    User,
)
from app.utils import current_time_utc


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/compliance", tags=["compliance"], dependencies=[Depends(no_store)])


@dataclass
class Access:
    user: User
    permissions: dict[PermissionKey, bool]


async def compliance_access(session: SessionDep, current_user: CurrentUser) -> Access:
    permissions = await get_effective_permission_map(session, current_user)
    if not permissions.get(PermissionKey.ACCESS_COMPLIANCE):
        raise HTTPException(403, "Compliance access is required.")
    return Access(current_user, permissions)


AccessDep = Annotated[Access, Depends(compliance_access)]
Offset = Annotated[int, Query(ge=0)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/instructions", response_model=InstructionsPage)
async def get_instructions(
    session: SessionDep, _access: AccessDep, offset: Offset = 0, limit: PageLimit = 25
) -> InstructionsPage:
    current = await current_instructions(session)
    rows = (
        await session.execute(
            select(ComplianceInstructionsVersion, User.name)
            .outerjoin(User, User.id == ComplianceInstructionsVersion.created_by_id)
            .order_by(ComplianceInstructionsVersion.number.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    result = InstructionsPage(
        current=await instructions_detail(session, current) if current else None,
        versions=[
            InstructionsSummary(
                id=version.id,
                number=version.number,
                created_at=version.created_at,
                author=author or "Former user",
            )
            for version, author in rows
        ],
        total=await session.scalar(select(func.count()).select_from(ComplianceInstructionsVersion))
        or 0,
    )
    await session.commit()
    return result


@router.get("/instructions/{version_id}", response_model=InstructionsDetail)
async def get_instruction_version(
    version_id: UUID, session: SessionDep, _access: AccessDep
) -> InstructionsDetail:
    version = await session.get(ComplianceInstructionsVersion, version_id)
    if version is None:
        raise HTTPException(404, "These saved instructions are unavailable.")
    result = await instructions_detail(session, version)
    await session.commit()
    return result


@router.post("/instructions", response_model=InstructionsDetail)
async def save_instructions(
    body: SaveInstructions, session: SessionDep, access: AccessDep
) -> InstructionsDetail:
    if not access.permissions.get(PermissionKey.EDIT_COMPLIANCE_INSTRUCTIONS):
        raise HTTPException(
            403, "Only the designated instruction owner can change these instructions."
        )
    await session.execute(text("SELECT pg_advisory_xact_lock(74218)"))
    current = await current_instructions(session)
    if body.base_version_id != (current.id if current else None):
        raise HTTPException(
            409,
            "The saved instructions have changed. "
            "Reopen the latest version before saving your changes.",
        )
    if body.restore_from_id is not None:
        restored = await session.get(ComplianceInstructionsVersion, body.restore_from_id)
        if restored is None:
            raise HTTPException(404, "The version to restore is unavailable.")
        content = restored.content
    else:
        content = cast(str, body.content)
    version = ComplianceInstructionsVersion(
        number=(current.number + 1) if current else 1, content=content, created_by_id=access.user.id
    )
    session.add(version)
    await session.flush()
    result = await instructions_detail(session, version)
    await session.commit()
    return result


async def _overlaps(session: SessionDep, access: Access, period: ScreeningPeriod) -> list[Overlap]:
    visible_screening_ids = (
        visible_items(access.user, access.permissions)
        .with_only_columns(ComplianceItem.screening_id)
        .distinct()
    )
    rows = (
        await session.execute(
            select(ComplianceScreening.id, ComplianceScreening.created_at)
            .where(
                ComplianceScreening.start_at <= period.end,
                ComplianceScreening.end_at >= period.start,
                or_(
                    ComplianceScreening.created_by_id == access.user.id,
                    ComplianceScreening.id.in_(visible_screening_ids),
                ),
            )
            .order_by(ComplianceScreening.created_at.desc())
            .limit(5)
        )
    ).all()
    return [Overlap(id=id_, created_at=created_at) for id_, created_at in rows]


@router.post("/screenings/preview", response_model=Preview)
async def preview_screening(
    body: ScreeningPeriod, session: SessionDep, access: AccessDep
) -> Preview:
    selected = source_selection(access.user, access.permissions, body.start, body.end).subquery()
    counts = (
        await session.execute(
            select(func.count(), func.count(func.distinct(selected.c.conversation_id))).select_from(
                selected
            )
        )
    ).one()
    version = await current_instructions(session)
    detail = await instructions_detail(session, version) if version else None
    result = Preview(
        messages=counts[0],
        conversations=counts[1],
        max_messages=settings.COMPLIANCE_MAX_MESSAGES,
        instructions=detail,
        overlaps=await _overlaps(session, access, body),
        worker_enabled=settings.COMPLIANCE_WORKER_ENABLED,
    )
    await session.commit()
    return result


@router.post("/screenings", response_model=ScreeningDetail)
async def start_screening(
    body: StartScreening, session: SessionDep, access: AccessDep
) -> ScreeningDetail:
    requested_at = current_time_utc()
    if not settings.COMPLIANCE_WORKER_ENABLED:
        raise HTTPException(
            503, "Transcript screening is temporarily unavailable. Please try again later."
        )
    await session.execute(text("SELECT pg_advisory_xact_lock(74218)"))
    existing = await session.get(ComplianceScreening, body.id)
    if existing is not None:
        if (
            existing.created_by_id,
            existing.instructions_version_id,
            existing.start_at,
            existing.end_at,
        ) != (access.user.id, body.instructions_version_id, body.start, body.end):
            raise HTTPException(
                409,
                "This screening request has already been used. "
                "Refresh before starting another screening.",
            )
        return await get_screening(body.id, session, access)
    current = await current_instructions(session)
    if current is None or current.id != body.instructions_version_id:
        raise HTTPException(
            409, "The instructions have changed. Refresh the preview before starting a screening."
        )
    active = await session.scalar(
        select(ComplianceItem.id)
        .where(
            ComplianceItem.requested_by_id == access.user.id,
            ComplianceItem.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    if active is not None:
        raise HTTPException(
            409,
            "You already have a screening in progress. "
            "Open it under Previous screenings before starting another.",
        )
    if not body.acknowledge_overlap and await _overlaps(session, access, body):
        raise HTTPException(
            409,
            "This period overlaps a previous screening. "
            "Confirm that you want a separate screening.",
        )
    try:
        screening = await admit_screening(
            session,
            screening_id=body.id,
            requester=access.user,
            permissions=access.permissions,
            instructions=current,
            start=body.start,
            end=body.end,
            requested_at=requested_at,
        )
    except NoEligibleMessagesError as exc:
        raise HTTPException(
            400, "There are no eligible assistant messages in this period within your chat access."
        ) from exc
    except ScreeningTooLargeError as exc:
        raise HTTPException(
            400,
            "Choose a shorter period: a screening can include at most "
            f"{settings.COMPLIANCE_MAX_MESSAGES:,} assistant messages.",
        ) from exc
    return await get_screening(screening.id, session, access)


@router.get("/screenings", response_model=ScreeningsPage)
async def list_screenings(
    session: SessionDep, access: AccessDep, offset: Offset = 0, limit: PageLimit = 25
) -> ScreeningsPage:
    statement = screening_rows(access.user, access.permissions)
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    result = ScreeningsPage(
        items=await summaries(
            session,
            statement.order_by(ComplianceScreening.created_at.desc(), ComplianceScreening.id)
            .offset(offset)
            .limit(limit),
        ),
        total=total,
    )
    await session.commit()
    return result


@router.get("/screenings/{screening_id}", response_model=ScreeningDetail)
async def get_screening(
    screening_id: UUID, session: SessionDep, access: AccessDep
) -> ScreeningDetail:
    summary = await require_screening(session, access.user, access.permissions, screening_id)
    screening = await session.get(ComplianceScreening, screening_id)
    if screening is None:
        raise HTTPException(404, "This screening is unavailable.")
    version = await session.get(ComplianceInstructionsVersion, summary.instructions_version_id)
    if version is None:
        raise HTTPException(404, "The instructions for this screening are unavailable.")
    failures = await failure_summaries(
        session,
        failure_rows(access.user, access.permissions, screening_id).order_by(
            Conversation.title.asc().nulls_last(),
            ComplianceItem.conversation_id,
            ComplianceItem.error_code,
        ),
        retry_supported=screening.screening_version == SCREENING_VERSION,
    )
    result = ScreeningDetail(
        **summary.model_dump(),
        instructions=await instructions_detail(session, version),
        failures=failures,
    )
    await session.commit()
    return result


@router.get("/screenings/{screening_id}/flags", response_model=FlagsPage)
async def list_flags(
    screening_id: UUID,
    session: SessionDep,
    access: AccessDep,
    offset: Offset = 0,
    limit: PageLimit = 25,
) -> FlagsPage:
    await require_screening(session, access.user, access.permissions, screening_id)
    statement = flag_rows(access.user, access.permissions, screening_id)
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    result = FlagsPage(
        items=await flag_summaries(
            session,
            statement.order_by(
                case((ComplianceFinding.review_state == "needs_review", 0), else_=1),
                Message.created_at.asc(),
                ComplianceFinding.created_at,
                ComplianceFinding.id,
            )
            .offset(offset)
            .limit(limit),
        ),
        total=total,
    )
    await session.commit()
    return result


@router.get("/screenings/{screening_id}/flags/{flag_id}", response_model=FlagDetail)
async def get_flag(
    screening_id: UUID, flag_id: UUID, session: SessionDep, access: AccessDep
) -> FlagDetail:
    row = (
        await session.execute(
            flag_rows(access.user, access.permissions, screening_id).where(
                ComplianceFinding.id == flag_id
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "This flag is unavailable or outside your chat access.")
    item, finding, title, message_id, conversation_id, message_at = row
    result = FlagDetail(
        chat=title or "Untitled chat",
        message_id=message_id,
        message_at=message_at,
        error=None,
        transcript=[],
        flag=None,
    )
    screening = await session.get(ComplianceScreening, screening_id)
    if screening is None:
        raise HTTPException(404, "This screening is unavailable.")
    try:
        result.transcript = await load_transcript(
            session, conversation_id, as_of=screening.created_at
        )
    except ScreeningUnavailableError as exc:
        result.error = error_message(exc.code)
        await session.commit()
        return result
    if item.input_hash is not None and transcript_hash(result.transcript) != item.input_hash:
        result.error = (
            "The source text has changed since this screening. "
            "Start a new screening; the previous evidence cannot be verified."
        )
        await session.commit()
        return result
    target = next((node for node in result.transcript if node.id == message_id), None)
    if target is None:
        result.error = error_message("invalid_context")
        await session.commit()
        return result
    if await session.get(ComplianceInstructionsVersion, screening.instructions_version_id) is None:
        raise HTTPException(404, "The instructions used are unavailable.")
    history = (
        await session.execute(
            select(ComplianceDecision, User.name)
            .outerjoin(User, User.id == ComplianceDecision.reviewer_id)
            .where(ComplianceDecision.finding_id == finding.id)
            .order_by(ComplianceDecision.revision.desc())
        )
    ).all()
    result.flag = FindingOut(
        id=finding.id,
        title=finding.title,
        explanation=finding.explanation,
        evidence=target.content[finding.evidence_start : finding.evidence_end],
        state=ReviewState(finding.review_state),
        revision=finding.decision_revision,
        decisions=[
            DecisionOut(
                state=DecisionState(decision.state),
                reviewer=author or "Former user",
                created_at=decision.created_at,
                revision=decision.revision,
            )
            for decision, author in history
        ],
    )
    await session.commit()
    return result


@router.post("/flags/{flag_id}/decision", response_model=DecisionOut)
async def decide(
    flag_id: UUID, body: DecisionInput, session: SessionDep, access: AccessDep
) -> DecisionOut:
    row = (
        await session.execute(
            visible_items(access.user, access.permissions)
            .join(ComplianceFinding, ComplianceFinding.item_id == ComplianceItem.id)
            .join(Message, Message.id == ComplianceFinding.message_id)
            .where(ComplianceFinding.id == flag_id)
            .with_only_columns(ComplianceItem, Message.conversation_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "This flag is unavailable or outside your chat access.")
    item, conversation_id = row
    source = await session.scalar(
        select(Conversation.id).where(Conversation.id == conversation_id).with_for_update(read=True)
    )
    if source is None:
        raise HTTPException(404, "The source transcript has been deleted.")
    screening = await session.get(ComplianceScreening, item.screening_id)
    if screening is None:
        raise HTTPException(404, "This screening is unavailable.")
    try:
        transcript = await load_transcript(
            session, conversation_id, as_of=screening.created_at, lock=True
        )
        valid_source = item.input_hash == transcript_hash(transcript)
    except ScreeningUnavailableError:
        valid_source = False
    if not valid_source:
        raise HTTPException(
            409,
            "The original evidence can no longer be verified. "
            "Start a new screening instead of deciding on changed evidence.",
        )
    finding = await session.scalar(
        select(ComplianceFinding).where(ComplianceFinding.id == flag_id).with_for_update()
    )
    if finding is None:
        raise HTTPException(404, "This flag is unavailable.")
    if finding.decision_revision != body.expected_revision:
        raise HTTPException(
            412,
            "A decision was saved while you were reviewing this flag. "
            "Reload the latest decision before saving.",
        )
    finding.decision_revision += 1
    finding.review_state = body.state.value
    decision = ComplianceDecision(
        finding_id=finding.id,
        reviewer_id=access.user.id,
        revision=finding.decision_revision,
        state=body.state.value,
    )
    session.add(decision)
    await session.flush()
    result = DecisionOut(
        state=body.state,
        reviewer=access.user.name,
        created_at=decision.created_at,
        revision=decision.revision,
    )
    await session.commit()
    return result


@router.post("/screenings/{screening_id}/retry")
async def retry_failed_items(
    screening_id: UUID, session: SessionDep, access: AccessDep
) -> dict[str, int]:
    if not settings.COMPLIANCE_WORKER_ENABLED:
        raise HTTPException(503, "Transcript screening is temporarily unavailable.")
    await require_screening(session, access.user, access.permissions, screening_id)
    screening = await session.get(ComplianceScreening, screening_id)
    if screening is None or screening.screening_version != SCREENING_VERSION:
        raise HTTPException(
            409, "The screening configuration has changed. Start a new screening for this period."
        )
    eligible = (
        visible_items(access.user, access.permissions)
        .with_only_columns(ComplianceItem.id)
        .where(
            ComplianceItem.screening_id == screening_id,
            ComplianceItem.status == "error",
            ComplianceItem.error_code.in_(RETRIABLE_ERROR_CODES),
            ComplianceItem.message_id.is_not(None),
        )
    )
    rows = list(
        (
            await session.execute(
                update(ComplianceItem)
                .where(ComplianceItem.id.in_(eligible))
                .values(
                    status="queued",
                    attempts=0,
                    requested_by_id=access.user.id,
                    error_code=None,
                    lease_token=None,
                    leased_until=None,
                )
                .returning(ComplianceItem.id, ComplianceItem.conversation_id)
            )
        ).all()
    )
    await session.commit()
    conversations = {conversation_id for _, conversation_id in rows if conversation_id is not None}
    return {"queued": len(rows), "conversations": len(conversations)}
