import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Any, Literal, NoReturn, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import BigInteger, case, false, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import CurrentUser, SessionDep
from app.api.grounding_agent import (
    GROUNDING_SOURCE_STATUS_FAILED,
    GROUNDING_SOURCE_STATUS_PENDING,
    GroundingSourceResultStatus,
    effective_grounding_source_status,
    mark_grounding_sources_failed,
    mark_grounding_sources_pending,
    select_and_store_grounding_sources,
)
from app.api.guardrails_failures import (
    GUARDRAILS_AGENT_NAMES,
    GUARDRAILS_URL_SPAN_NAME,
    GuardrailsTraceSpan,
    dump_guardrails_failures_from_spans,
)
from app.api.message_sources import (
    MessageSourceUsed,
    filter_sources_by_keys,
    get_tool_sources_used_for_message,
    with_canned_response_source_candidate,
)
from app.api.response_costs import (
    ResponseCostSpan,
    response_cost_span_condition,
    summarize_response_costs,
    uncached_input_tokens,
)
from app.api.routes.owner_group_filter import (
    OwnerGroup,
    build_owner_group_filter,
    validate_exclusive_user_filters,
)
from app.chat.engine import (
    MessageOut,
    ModelSettings,
    handle_conversation_turn,
    handle_investigation_turn,
)
from app.chat.engine_utils import ReasoningEffort
from app.chat.internal_summary import summarize_internal_conversation
from app.chat.title import (
    build_fallback_title,
    generate_conversation_title,
    generate_conversation_title_from_transcript,
)
from app.chat.tree_utils import get_current_branch_path
from app.core.config import settings
from app.core.db import async_session_factory, get_session
from app.core.rbac import (
    PermissionKey,
    get_allowed_chat_owner_group_slugs,
    get_effective_permission_map,
)
from app.models import (
    AssistantMessageMetadata,
    ChatGenerationAttempt,
    Conversation,
    Message,
    OtelSpan,
    PromptSetScope,
    RbacGroup,
    User,
)
from app.otel import (
    mark_current_span_for_otel_export,
    otel_export_scope,
    span_persistence_scope,
    wait_for_pending_spans,
)
from app.prompt_sets import get_template_filenames_for_scope, hash_prompt_templates
from app.utils import current_time_utc, logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_background_tasks: set[asyncio.Task[Any]] = set()


def _track_background_task(task: asyncio.Task[Any]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_handle_background_task_done)


def _handle_background_task_done(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Background task failed", exc_info=(type(exception), exception, exception.__traceback__)
        )


router = APIRouter(tags=["messages"])

_PREVIEW_MAX_LENGTH = 220
_MESSAGE_GENERATION_FAILED_MESSAGE = "The response could not be completed."
_GENERATION_ATTEMPT_PENDING = "pending"
_GENERATION_ATTEMPT_COMPLETED = "completed"
_GENERATION_ATTEMPT_FAILED = "failed"
GenerationAttemptStatus = Literal["pending", "completed", "failed"]


def _format_sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def generation_request_fingerprint(request: ChatRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"generation_attempt_id"}, exclude_unset=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode()).hexdigest()


def _visible_assistant_content(message: Message | MessageOut) -> str:
    if message.guardrails_blocked:
        return message.guardrails_blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE
    return message.content


def _minimal_assistant_payload(
    *, user_message_id: UUID, assistant_message: Message | MessageOut
) -> dict[str, Any]:
    assert assistant_message.conversation_id is not None
    return {
        "conversation_id": str(assistant_message.conversation_id),
        "user_message_id": str(user_message_id),
        "assistant_message_id": str(assistant_message.id),
        "assistant_message": _visible_assistant_content(assistant_message),
        "guardrails_blocked": assistant_message.guardrails_blocked,
        "guardrails_blocked_message": assistant_message.guardrails_blocked_message,
        "guardrails_failures": [],
        "parent_message_id": (
            str(assistant_message.parent_id) if assistant_message.parent_id is not None else None
        ),
        "generation_time_ms": None,
        "generation_timing": None,
        "response_cost": None,
        "response_usage": None,
        "response_cost_breakdown": None,
        "tool_sources_used": [],
        "grounding_sources_used": [],
        "grounding_source_status": None,
    }


async def _finalize_failed_generation_attempt(
    session: AsyncSession, *, generation_attempt_id: UUID
) -> ChatGenerationAttempt | None:
    try:
        attempt = await session.get(
            ChatGenerationAttempt, generation_attempt_id, populate_existing=True
        )
        if attempt is None:
            return None
        if attempt.status == _GENERATION_ATTEMPT_PENDING:
            attempt.status = _GENERATION_ATTEMPT_FAILED
            await session.commit()
    except Exception:
        logger.exception("Failed to finalize generation attempt %s", generation_attempt_id)
        with suppress(Exception):
            await session.rollback()
        return None
    else:
        return attempt


def _require_generation_attempt(attempt: ChatGenerationAttempt | None) -> ChatGenerationAttempt:
    if attempt is None:
        raise RuntimeError("Generation attempt disappeared before completion")
    return attempt


async def _ensure_generation_attempt_access(
    session: AsyncSession,
    attempt: ChatGenerationAttempt,
    current_user: CurrentUser,
    permission_map: dict[PermissionKey, bool],
) -> Conversation:
    if attempt.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Generation attempt not found")
    conversation = await session.get(Conversation, attempt.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _ensure_conversation_author_access(conversation, current_user)
    if conversation.kind == "investigation":
        _ensure_investigation_access(permission_map)
    return conversation


async def _get_generation_attempt_if_exists(
    session: AsyncSession,
    *,
    generation_attempt_id: UUID,
    current_user: CurrentUser,
    request_fingerprint: str,
    permission_map: dict[PermissionKey, bool],
) -> ChatGenerationAttempt | None:
    attempt = await session.get(ChatGenerationAttempt, generation_attempt_id)
    if attempt is None:
        return None
    await _ensure_generation_attempt_access(session, attempt, current_user, permission_map)
    if attempt.request_fingerprint != request_fingerprint:
        raise HTTPException(
            status_code=409, detail="Generation attempt payload does not match the original request"
        )
    return attempt


def _raise_existing_generation_attempt(attempt: ChatGenerationAttempt) -> NoReturn:
    if attempt.status == _GENERATION_ATTEMPT_PENDING:
        detail = "Generation attempt is still pending"
    elif attempt.status == _GENERATION_ATTEMPT_COMPLETED:
        detail = "Generation attempt is already completed"
    elif attempt.status == _GENERATION_ATTEMPT_FAILED:
        detail = "Generation attempt has already failed"
    else:
        raise HTTPException(status_code=500, detail="Invalid generation attempt status")
    raise HTTPException(status_code=409, detail=detail)


class DraftPromptTemplateIn(BaseModel):
    filename: str
    content: str


class ChatRequest(BaseModel):
    user_prompt: str
    generation_attempt_id: UUID | None = None
    conversation_id: UUID | None = None
    parent_message_id: UUID | None = None
    prompt_set_version_id: UUID | None = None
    draft_prompt_templates: list[DraftPromptTemplateIn] | None = None
    chatbot_model: str | None = None
    guardrail_model: str | None = None
    chatbot_reasoning_effort: ReasoningEffort | None = None
    guardrail_reasoning_effort: ReasoningEffort | None = None
    conversation_kind: Literal["chat", "investigation"] = "chat"
    is_regeneration: bool = False


class ChatResponse(BaseModel):
    conversation_id: UUID
    conversation_title: str | None
    user_message_id: UUID
    assistant_message_id: UUID
    assistant_message: str
    parent_message_id: UUID | None
    tool_sources_used: list[MessageSourceUsed] = []
    grounding_sources_used: list[MessageSourceUsed] = []
    grounding_source_status: str | None = None


class GroundingSourcesResponse(BaseModel):
    assistant_message_id: UUID
    grounding_sources_used: list[MessageSourceUsed] = []
    grounding_source_status: GroundingSourceResultStatus


class GenerationAttemptResponse(BaseModel):
    generation_attempt_id: UUID
    status: GenerationAttemptStatus
    conversation_id: UUID
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None


class MessageListItem(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    content_preview: str
    content_length: int
    conversation_title: str | None = None
    conversation_summary: str | None = None
    is_public: bool
    conversation_user_name: str | None = None
    conversation_user_email: str | None = None
    generation_time_ms: int | None = None
    input_tokens: int | None = None
    uncached_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None
    response_cost: float | None = None
    tool_call_count: int = 0
    guardrail_failure_count: int = 0
    guardrails_blocked: bool = False
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageListPage(BaseModel):
    items: list[MessageListItem]
    total: int


@dataclass(frozen=True, slots=True)
class _MessageTraceSummary:
    input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None
    response_cost: float | None = None
    guardrail_failure_count: int = 0
    trace_id: str | None = None
    span_id: str | None = None


async def _get_message_trace_summaries(
    session: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, _MessageTraceSummary]:
    if not message_ids:
        return {}

    latest_span = (
        select(OtelSpan.message_id, OtelSpan.trace_id, OtelSpan.span_id)
        .where(OtelSpan.message_id.in_(message_ids))
        .order_by(
            OtelSpan.message_id, OtelSpan.start_time.desc().nullslast(), OtelSpan.created_at.desc()
        )
        .distinct(OtelSpan.message_id)
        .subquery()
    )
    trace_span = aliased(OtelSpan)
    cost_span_condition = (
        trace_span.is_ai.is_(True)
        & trace_span.is_embedding.is_not(True)
        & response_cost_span_condition(trace_span)
    )
    cache_read_tokens = func.coalesce(
        func.jsonb_extract_path_text(
            trace_span.attributes, "gen_ai.usage.cache_read.input_tokens"
        ).cast(BigInteger),
        0,
    )
    rows = (
        await session.execute(
            select(
                latest_span.c.message_id,
                latest_span.c.trace_id,
                latest_span.c.span_id,
                func.sum(trace_span.input_tokens).filter(cost_span_condition).label("input_tokens"),
                func.sum(cache_read_tokens)
                .filter(cost_span_condition)
                .label("cache_read_input_tokens"),
                func.sum(trace_span.output_tokens)
                .filter(cost_span_condition)
                .label("output_tokens"),
                func.sum(trace_span.total_cost).filter(cost_span_condition).label("response_cost"),
                func.count()
                .filter(
                    func.jsonb_extract_path_text(
                        trace_span.attributes, "app.guardrails.result.is_valid"
                    )
                    == "false"
                )
                .label("guardrail_failure_count"),
            )
            .outerjoin(trace_span, trace_span.trace_id == latest_span.c.trace_id)
            .group_by(latest_span.c.message_id, latest_span.c.trace_id, latest_span.c.span_id)
        )
    ).all()
    return {
        message_id: _MessageTraceSummary(
            input_tokens=int(input_tokens) if input_tokens is not None else None,
            cache_read_input_tokens=(
                int(cache_read_input_tokens) if cache_read_input_tokens is not None else None
            ),
            output_tokens=int(output_tokens) if output_tokens is not None else None,
            response_cost=float(response_cost) if response_cost is not None else None,
            guardrail_failure_count=int(guardrail_failure_count),
            trace_id=trace_id,
            span_id=span_id,
        )
        for (
            message_id,
            trace_id,
            span_id,
            input_tokens,
            cache_read_input_tokens,
            output_tokens,
            response_cost,
            guardrail_failure_count,
        ) in rows
    }


def _format_message_preview(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) > _PREVIEW_MAX_LENGTH:
        return normalized[:_PREVIEW_MAX_LENGTH] + "..."
    return normalized


def _is_admin_user(current_user: CurrentUser) -> bool:
    return current_user.group.slug in {"admin", "dev"}


def _internal_visibility_condition(
    current_user: CurrentUser, *, permission_map: dict[PermissionKey, bool]
) -> Any:
    conditions: list[Any] = []

    if permission_map.get(PermissionKey.CHATS_VIEW_OWN, False):
        conditions.append(Conversation.user_id == current_user.id)

    allowed_group_slugs = get_allowed_chat_owner_group_slugs(permission_map)
    if allowed_group_slugs:
        conditions.append(RbacGroup.slug.in_(sorted(allowed_group_slugs)))

    if not conditions:
        return false()

    return or_(*conditions)


def _get_platform_scope(current_user: CurrentUser, platform: str | None) -> tuple[bool, bool]:
    if platform is not None and platform not in {"internal", "public"}:
        raise HTTPException(status_code=400, detail="Invalid platform")

    can_view_public = _is_admin_user(current_user)
    if platform == "public" and not can_view_public:
        raise HTTPException(status_code=403, detail="Access denied")

    include_internal = platform in (None, "internal")
    include_public = can_view_public and platform in (None, "public")
    return include_internal, include_public


def _seconds_to_ms(value: float | None) -> int | None:
    return round(value * 1000) if value is not None else None


def _seconds_list_to_ms(values: list[float] | None) -> list[int] | None:
    return [round(value * 1000) for value in values] if values else None


def _get_model_name(model_settings: ModelSettings | dict[str, Any] | None) -> str | None:
    if model_settings is None:
        return None
    model: Any = (
        model_settings.get("model") if isinstance(model_settings, dict) else model_settings.model
    )
    return model if isinstance(model, str) and model.strip() != "" else None


def _build_generation_timing_payload(message: Any) -> dict[str, Any] | None:
    timing_metadata = getattr(message, "metadata", None)
    if timing_metadata is None:
        return None

    chatbot_times_ms = _seconds_list_to_ms(timing_metadata.chatbot_times)
    guardrail_times_ms = _seconds_list_to_ms(timing_metadata.guardrail_times)
    chatbot_time_ms = (
        sum(chatbot_times_ms)
        if chatbot_times_ms is not None and len(chatbot_times_ms) > 1
        else _seconds_to_ms(timing_metadata.chatbot_time)
    )

    raw_payload = {
        "total_time_ms": _seconds_to_ms(timing_metadata.total_time),
        "chatbot_time_ms": chatbot_time_ms,
        "guardrail_time_ms": _seconds_to_ms(timing_metadata.guardrail_time),
        "chatbot_times_ms": chatbot_times_ms,
        "guardrail_times_ms": guardrail_times_ms,
        "chatbot_model": _get_model_name(timing_metadata.chatbot_model_settings),
        "guardrail_model": _get_model_name(timing_metadata.guardrail_model_settings),
    }
    payload = {key: value for key, value in raw_payload.items() if value is not None}

    return payload or None


def _ensure_investigation_access(permission_map: dict[PermissionKey, bool]) -> None:
    if not permission_map.get(PermissionKey.ACCESS_INVESTIGATIONS, False):
        raise HTTPException(status_code=403, detail="Access denied")


def _ensure_conversation_author_access(
    conversation: Conversation, current_user: CurrentUser
) -> None:
    if conversation.is_public or conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")


async def _get_stream_conversation_or_404(
    session: SessionDep | Any, conversation_id: UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _get_model_settings(
    request: ChatRequest, *, conversation_kind: Literal["chat", "investigation"]
) -> tuple[ModelSettings, ModelSettings]:
    is_investigation = conversation_kind == "investigation"
    investigation_reasoning_effort: ReasoningEffort = settings.INVESTIGATION_REASONING_EFFORT
    chatbot = ModelSettings(
        model=request.chatbot_model
        or (settings.INVESTIGATION_MODEL if is_investigation else settings.CHATBOT_MODEL),
        temperature=settings.CHATBOT_MODEL_TEMPERATURE or None,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS or None,
        reasoning_effort=request.chatbot_reasoning_effort
        or (investigation_reasoning_effort if is_investigation else None),
        azure_service_tier=(None if is_investigation else settings.CHATBOT_AZURE_SERVICE_TIER),
    )
    guardrail = ModelSettings(
        model=request.guardrail_model or settings.GUARDRAIL_MODEL,
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE or None,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS or None,
        reasoning_effort=request.guardrail_reasoning_effort,
        azure_service_tier=settings.GUARDRAIL_AZURE_SERVICE_TIER,
    )
    return chatbot, guardrail


def _normalize_draft_prompt_templates(
    request: ChatRequest,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    if request.draft_prompt_templates is None:
        return None, None

    if request.conversation_kind != "chat":
        raise HTTPException(
            status_code=400, detail="Draft instruction testing is only supported for chat"
        )
    if request.prompt_set_version_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Use either draft instructions or a saved version of the instructions, not both",
        )

    expected_templates = set(
        get_template_filenames_for_scope(PromptSetScope.ASSISTANT, is_internal=True)
    )
    submitted: dict[str, str] = {}
    for template in request.draft_prompt_templates:
        filename = template.filename.strip()
        if filename in submitted:
            raise HTTPException(status_code=400, detail="Duplicate draft templates provided")
        submitted[filename] = template.content

    submitted_templates = set(submitted)
    missing = sorted(expected_templates - submitted_templates)
    extra = sorted(submitted_templates - expected_templates)
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Missing draft templates: {', '.join(missing)}"
        )
    if extra:
        raise HTTPException(
            status_code=400, detail=f"Unexpected draft templates: {', '.join(extra)}"
        )

    prompt_hash = hash_prompt_templates(submitted)
    prompt_context: dict[str, Any] = {
        "source": "draft",
        "scope": PromptSetScope.ASSISTANT.value,
        "is_internal": True,
        "hash": prompt_hash,
        "template_filenames": sorted(submitted),
    }
    return submitted, prompt_context


def _ensure_draft_context_is_allowed(
    conversation: Conversation, prompt_context: dict[str, Any] | None
) -> None:
    if conversation.prompt_source == "draft":
        if prompt_context is None:
            raise HTTPException(
                status_code=400,
                detail="Draft instruction chats must be continued from the Instructions page",
            )
        return

    if prompt_context is not None:
        raise HTTPException(
            status_code=400, detail="Draft instructions can only start or continue draft test chats"
        )


@router.get("/messages", response_model=MessageListPage)
async def list_messages(
    session: SessionDep,
    current_user: CurrentUser,
    platform: Annotated[Literal["internal", "public"] | None, Query()] = None,
    role: Annotated[Literal["user", "assistant", "all"], Query()] = "assistant",
    search: Annotated[str | None, Query()] = None,
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[str, Query()] = "created_at",
    descending: Annotated[bool, Query()] = True,
) -> MessageListPage:
    permission_map = await get_effective_permission_map(session, current_user)
    if not permission_map.get(PermissionKey.ACCESS_MESSAGES, False):
        raise HTTPException(status_code=403, detail="Access denied")

    include_internal, include_public = _get_platform_scope(current_user, platform)
    can_view_response_cost = permission_map.get(PermissionKey.CHAT_VIEW_RESPONSE_COST, False)
    internal_visibility_condition = _internal_visibility_condition(
        current_user, permission_map=permission_map
    )

    owner_user_alias = aliased(User)
    conversation_user_name = owner_user_alias.name.label("conversation_user_name")
    conversation_user_email = owner_user_alias.email.label("conversation_user_email")
    content_length = func.char_length(Message.content).label("content_length")
    generation_time_ms = (AssistantMessageMetadata.total_time * 1000).label("generation_time_ms")
    latest_trace_span_alias = aliased(OtelSpan)
    token_span_alias = aliased(OtelSpan)
    guardrail_span_alias = aliased(OtelSpan)
    latest_trace_id = (
        select(latest_trace_span_alias.trace_id)
        .where(latest_trace_span_alias.message_id == Message.id)
        .order_by(
            latest_trace_span_alias.start_time.desc().nullslast(),
            latest_trace_span_alias.created_at.desc(),
        )
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    )
    input_tokens = (
        select(func.sum(token_span_alias.input_tokens))
        .where(
            token_span_alias.trace_id == latest_trace_id,
            token_span_alias.is_ai.is_(True),
            token_span_alias.is_embedding.is_not(True),
            response_cost_span_condition(token_span_alias),
        )
        .correlate(Message)
        .scalar_subquery()
    ).label("input_tokens")
    cache_read_input_tokens = (
        select(
            func.sum(
                func.coalesce(
                    func.jsonb_extract_path_text(
                        token_span_alias.attributes, "gen_ai.usage.cache_read.input_tokens"
                    ).cast(BigInteger),
                    0,
                )
            )
        )
        .where(
            token_span_alias.trace_id == latest_trace_id,
            token_span_alias.is_ai.is_(True),
            token_span_alias.is_embedding.is_not(True),
            response_cost_span_condition(token_span_alias),
        )
        .correlate(Message)
        .scalar_subquery()
    ).label("cache_read_input_tokens")
    uncached_input_token_count = case(
        (input_tokens.is_(None), None),
        else_=func.greatest(input_tokens - func.coalesce(cache_read_input_tokens, 0), 0),
    ).label("uncached_input_tokens")
    response_cost = (
        select(func.sum(token_span_alias.total_cost))
        .where(
            token_span_alias.trace_id == latest_trace_id,
            token_span_alias.is_ai.is_(True),
            token_span_alias.is_embedding.is_not(True),
            response_cost_span_condition(token_span_alias),
        )
        .correlate(Message)
        .scalar_subquery()
    ).label("response_cost")
    output_tokens = (
        select(func.sum(token_span_alias.output_tokens))
        .where(
            token_span_alias.trace_id == latest_trace_id,
            token_span_alias.is_ai.is_(True),
            token_span_alias.is_embedding.is_not(True),
            response_cost_span_condition(token_span_alias),
        )
        .correlate(Message)
        .scalar_subquery()
    ).label("output_tokens")
    tool_call_count = case(
        (
            func.jsonb_typeof(AssistantMessageMetadata.tool_calls) == "array",
            func.jsonb_array_length(
                func.jsonb_path_query_array(
                    AssistantMessageMetadata.tool_calls,
                    literal_column("'$[*].tool_calls[*]'::jsonpath"),
                )
            ),
        ),
        else_=0,
    ).label("tool_call_count")
    guardrail_failure_count = (
        select(func.count())
        .where(
            guardrail_span_alias.trace_id == latest_trace_id,
            func.jsonb_extract_path_text(
                guardrail_span_alias.attributes, "app.guardrails.result.is_valid"
            )
            == "false",
        )
        .correlate(Message)
        .scalar_subquery()
    ).label("guardrail_failure_count")
    base_stmt = (
        select(
            Message,
            Conversation,
            content_length,
            conversation_user_name,
            conversation_user_email,
            generation_time_ms,
            input_tokens,
            uncached_input_token_count,
            cache_read_input_tokens,
            output_tokens,
            response_cost,
            tool_call_count,
            guardrail_failure_count,
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .outerjoin(owner_user_alias, Conversation.user_id == owner_user_alias.id)
        .outerjoin(RbacGroup, owner_user_alias.group_id == RbacGroup.id)
        .outerjoin(AssistantMessageMetadata, AssistantMessageMetadata.message_id == Message.id)
    )

    platform_conditions: list[Any] = []
    if include_internal:
        platform_conditions.append(
            Conversation.is_public.is_(False) & internal_visibility_condition
        )
    if include_public:
        platform_conditions.append(Conversation.is_public.is_(True))
    if platform_conditions:
        base_stmt = base_stmt.where(or_(*platform_conditions))
    base_stmt = base_stmt.where(Conversation.kind == "chat")

    if role != "all":
        base_stmt = base_stmt.where(Message.role == role)
    if start is not None:
        base_stmt = base_stmt.where(Message.created_at >= start)
    if end is not None:
        base_stmt = base_stmt.where(Message.created_at <= end)
    if search is not None and search.strip() != "":
        pattern = f"%{search.strip()}%"
        base_stmt = base_stmt.where(
            or_(
                Message.content.ilike(pattern),
                Conversation.title.ilike(pattern),
                Conversation.summary.ilike(pattern),
                owner_user_alias.name.ilike(pattern),
                owner_user_alias.email.ilike(pattern),
            )
        )

    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)

    if user_email is not None and user_email.strip() != "":
        normalized_email = user_email.strip()
        user_conditions: list[Any] = []
        if include_internal:
            user_conditions.append(owner_user_alias.email == normalized_email)
        base_stmt = base_stmt.where(or_(*user_conditions) if user_conditions else false())

    base_stmt = build_owner_group_filter(
        base_stmt,
        owner_group=user_group,
        include_internal=include_internal,
        permission_map=permission_map,
    )

    # Trace diagnostics do not affect the number of visible messages.
    filtered_ids_stmt = base_stmt.with_only_columns(Message.id, maintain_column_froms=True)

    sort_map: dict[str, Any] = {
        "content_length": content_length,
        "created_at": Message.created_at,
        "updated_at": Message.updated_at,
        "role": Message.role,
        "conversation_title": Conversation.title,
        "generation_time_ms": generation_time_ms,
        "input_tokens": input_tokens,
        "uncached_input_tokens": uncached_input_token_count,
        "cache_read_input_tokens": cache_read_input_tokens,
        "output_tokens": output_tokens,
        "tool_call_count": tool_call_count,
        "guardrail_failure_count": guardrail_failure_count,
        "guardrails_blocked": Message.guardrails_blocked,
    }
    if can_view_response_cost:
        sort_map["response_cost"] = response_cost
    sort_column = sort_map.get(sort_by, Message.created_at)
    sort_expression = sort_column.desc() if descending else sort_column.asc()
    if sort_by in {
        "input_tokens",
        "uncached_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "response_cost",
    }:
        sort_expression = sort_expression.nullslast()
    # Select the page before loading details. Trace sorts add only their requested
    # scalar expression to this query; all returned diagnostics are page-scoped.
    page_rows = (
        await session.execute(
            filtered_ids_stmt.add_columns(func.count().over().label("page_total"))
            .order_by(sort_expression)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if page_rows:
        total = int(page_rows[0].page_total)
        page_ids = [row[0] for row in page_rows]
    else:
        total_stmt = select(func.count()).select_from(filtered_ids_stmt.subquery())
        total = (await session.execute(total_stmt)).scalar() or 0
        response = MessageListPage(total=total, items=[])
        # Preserve the total while releasing the reserved connection before serialization.
        await session.commit()
        return response

    page_details_stmt = base_stmt.with_only_columns(
        Message,
        Conversation,
        content_length,
        conversation_user_name,
        conversation_user_email,
        generation_time_ms,
        tool_call_count,
        maintain_column_froms=True,
    ).where(Message.id.in_(page_ids))
    page_rows = (await session.execute(page_details_stmt)).all()
    page_rows_by_id = {row[0].id: row for row in page_rows}
    ordered_page_rows = [
        page_rows_by_id[message_id] for message_id in page_ids if message_id in page_rows_by_id
    ]
    trace_summaries = await _get_message_trace_summaries(session, page_ids)

    items: list[MessageListItem] = []
    for (
        message,
        conversation,
        content_length_value,
        conversation_user_name_value,
        conversation_user_email_value,
        generation_time_ms_value,
        tool_call_count_value,
    ) in ordered_page_rows:
        trace_summary = trace_summaries.get(message.id, _MessageTraceSummary())
        items.append(
            MessageListItem(
                id=message.id,
                conversation_id=conversation.id,
                role=message.role,
                content=message.content,
                content_preview=_format_message_preview(message.content),
                content_length=content_length_value,
                conversation_title=conversation.title,
                conversation_summary=conversation.summary,
                is_public=conversation.is_public,
                conversation_user_name=conversation_user_name_value,
                conversation_user_email=conversation_user_email_value,
                generation_time_ms=(
                    round(generation_time_ms_value)
                    if generation_time_ms_value is not None
                    else None
                ),
                input_tokens=trace_summary.input_tokens,
                uncached_input_tokens=uncached_input_tokens(
                    trace_summary.input_tokens, trace_summary.cache_read_input_tokens
                ),
                cache_read_input_tokens=trace_summary.cache_read_input_tokens,
                output_tokens=trace_summary.output_tokens,
                response_cost=trace_summary.response_cost if can_view_response_cost else None,
                tool_call_count=tool_call_count_value,
                guardrail_failure_count=trace_summary.guardrail_failure_count,
                guardrails_blocked=message.guardrails_blocked,
                trace_id=trace_summary.trace_id,
                span_id=trace_summary.span_id,
                created_at=message.created_at,
                updated_at=message.updated_at,
            )
        )
    response = MessageListPage(total=total, items=items)
    # Release the reserved connection before FastAPI validates and serializes the response.
    await session.commit()
    return response


def _guardrails_trace_span_condition() -> Any:
    return or_(
        OtelSpan.name == GUARDRAILS_URL_SPAN_NAME,
        func.jsonb_extract_path_text(OtelSpan.attributes, "gen_ai.agent.name").in_(
            GUARDRAILS_AGENT_NAMES
        ),
    )


async def _get_message_response_diagnostics(
    message_id: UUID, *, include_cost: bool, include_guardrails_failures: bool
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "response_cost": None,
        "response_usage": None,
        "response_cost_breakdown": None,
        "guardrails_failures": None,
    }
    if not include_cost and not include_guardrails_failures:
        return diagnostics

    async with get_session() as session:
        latest_trace_id = (
            await session.execute(
                select(OtelSpan.trace_id)
                .where(OtelSpan.message_id == message_id)
                .order_by(OtelSpan.start_time.desc().nullslast(), OtelSpan.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_trace_id is None:
            return diagnostics

        guardrails_spans: list[GuardrailsTraceSpan] = []
        if include_guardrails_failures:
            guardrails_span_rows = (
                await session.execute(
                    select(
                        OtelSpan.trace_id,
                        OtelSpan.span_id,
                        OtelSpan.name,
                        OtelSpan.start_time,
                        OtelSpan.span_time,
                        OtelSpan.created_at,
                        OtelSpan.attributes,
                    )
                    .where(OtelSpan.trace_id == latest_trace_id)
                    .where(_guardrails_trace_span_condition())
                )
            ).all()
            guardrails_spans = [GuardrailsTraceSpan(*row) for row in guardrails_span_rows]

        cost_span_rows: list[
            tuple[float | None, int | None, int | None, dict[str, Any] | None, datetime | None]
        ] = []
        if include_cost:
            raw_cost_rows = (
                await session.execute(
                    select(
                        OtelSpan.total_cost,
                        OtelSpan.input_tokens,
                        OtelSpan.output_tokens,
                        OtelSpan.attributes,
                        OtelSpan.created_at,
                    ).where(
                        OtelSpan.trace_id == latest_trace_id,
                        OtelSpan.is_ai.is_(True),
                        OtelSpan.is_embedding.is_not(True),
                        response_cost_span_condition(OtelSpan),
                    )
                )
            ).all()
            cost_span_rows = [
                cast(
                    tuple[
                        float | None, int | None, int | None, dict[str, Any] | None, datetime | None
                    ],
                    tuple(row),
                )
                for row in raw_cost_rows
            ]

    if include_guardrails_failures:
        diagnostics["guardrails_failures"] = dump_guardrails_failures_from_spans(guardrails_spans)
    if not include_cost:
        return diagnostics

    cost_summary = summarize_response_costs(
        [
            ResponseCostSpan(
                total_cost=total_cost_value,
                input_tokens=span_input_tokens,
                output_tokens=span_output_tokens,
                attributes=attributes,
                created_at=span_created_at,
            )
            for (
                total_cost_value,
                span_input_tokens,
                span_output_tokens,
                attributes,
                span_created_at,
            ) in cost_span_rows
        ]
    )

    diagnostics["response_cost"] = cost_summary.response_cost
    diagnostics["response_usage"] = (
        None
        if cost_summary.input_tokens is None
        and cost_summary.cache_read_input_tokens is None
        and cost_summary.output_tokens is None
        else {
            "input_tokens": cost_summary.input_tokens,
            "uncached_input_tokens": uncached_input_tokens(
                cost_summary.input_tokens, cost_summary.cache_read_input_tokens
            ),
            "cache_read_input_tokens": cost_summary.cache_read_input_tokens,
            "output_tokens": cost_summary.output_tokens,
        }
    )
    diagnostics["response_cost_breakdown"] = cost_summary.cost_breakdown
    return diagnostics


async def _persist_conversation_title(conversation_id: UUID, title: str) -> None:
    async with get_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            logger.warning(
                "Conversation not found while updating title",
                extra={"conversation_id": str(conversation_id)},
            )
            return
        conversation.title = title


async def _generate_initial_title(
    conversation_id: UUID,
    user_prompt: str,
    *,
    is_internal: bool,
    on_title: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    title = await generate_conversation_title(
        user_prompt, conversation_id=conversation_id, is_internal=is_internal
    )
    await _persist_conversation_title(conversation_id, title)
    if on_title is not None:
        await on_title(title)


async def _generate_transcript_title(
    conversation_id: UUID,
    user_prompt: str,
    assistant_message: str,
    *,
    assistant_message_id: UUID,
    is_internal: bool,
    on_title: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    role_label = "Staff" if is_internal else "User"
    transcript = f"{role_label}: {user_prompt}\n\nAssistant: {assistant_message}"
    fallback = build_fallback_title(user_prompt)
    title = await generate_conversation_title_from_transcript(
        transcript,
        conversation_id=conversation_id,
        trigger_message_id=assistant_message_id,
        is_internal=is_internal,
        fallback=fallback,
    )
    await _persist_conversation_title(conversation_id, title)
    if on_title is not None:
        await on_title(title)


async def _persist_grounding_source_failure(assistant_message_id: UUID) -> None:
    try:
        async with get_session() as grounding_session:
            await mark_grounding_sources_failed(
                grounding_session, assistant_message_id=assistant_message_id
            )
    except Exception:
        logger.exception(
            "Failed to persist grounding source failure for assistant message %s",
            assistant_message_id,
        )


async def _select_and_store_grounding_sources_in_background(
    *,
    assistant_message_id: UUID,
    user_message_id: UUID,
    assistant_answer: str,
    sources: list[MessageSourceUsed],
) -> tuple[list[MessageSourceUsed], GroundingSourceResultStatus]:
    try:
        async with get_session() as grounding_session:
            selected_keys, status = await select_and_store_grounding_sources(
                grounding_session,
                assistant_message_id=assistant_message_id,
                user_message_id=user_message_id,
                assistant_answer=assistant_answer,
                sources=sources,
            )
        return filter_sources_by_keys(sources, selected_keys), status
    except asyncio.CancelledError:
        await _persist_grounding_source_failure(assistant_message_id)
        raise
    except Exception:
        logger.exception(
            "Grounding source processing failed for assistant message %s", assistant_message_id
        )
        await _persist_grounding_source_failure(assistant_message_id)
        return [], GROUNDING_SOURCE_STATUS_FAILED


@router.get(
    "/messages/internal/generation-attempts/{generation_attempt_id}",
    response_model=GenerationAttemptResponse,
)
async def get_internal_generation_attempt(
    generation_attempt_id: UUID, session: SessionDep, current_user: CurrentUser
) -> GenerationAttemptResponse:
    attempt = await session.get(ChatGenerationAttempt, generation_attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Generation attempt not found")
    permission_map = await get_effective_permission_map(session, current_user)
    await _ensure_generation_attempt_access(session, attempt, current_user, permission_map)
    return GenerationAttemptResponse(
        generation_attempt_id=attempt.id,
        status=cast("GenerationAttemptStatus", attempt.status),
        conversation_id=attempt.conversation_id,
        user_message_id=attempt.user_message_id,
        assistant_message_id=attempt.assistant_message_id,
    )


@router.post(
    "/messages/internal/{message_id}/grounding/retry", response_model=GroundingSourcesResponse
)
async def retry_internal_message_grounding(
    message_id: UUID, session: SessionDep, current_user: CurrentUser
) -> GroundingSourcesResponse:
    mark_current_span_for_otel_export()
    permission_map = await get_effective_permission_map(session, current_user)
    if not permission_map.get(PermissionKey.CHAT_VIEW_SOURCES, False):
        raise HTTPException(status_code=403, detail="Access denied")

    assistant_message = await session.get(Message, message_id)
    if assistant_message is None or assistant_message.role != "assistant":
        raise HTTPException(status_code=404, detail="Assistant message not found")

    conversation = await _get_stream_conversation_or_404(session, assistant_message.conversation_id)
    _ensure_conversation_author_access(conversation, current_user)
    if conversation.kind != "chat":
        raise HTTPException(
            status_code=400,
            detail="Source grounding retry is supported only for chat conversations",
        )

    metadata = await session.scalar(
        select(AssistantMessageMetadata).where(
            AssistantMessageMetadata.message_id == assistant_message.id
        )
    )
    if metadata is None:
        raise HTTPException(status_code=404, detail="Assistant message metadata not found")
    if effective_grounding_source_status(metadata) != GROUNDING_SOURCE_STATUS_FAILED:
        raise HTTPException(status_code=409, detail="Source grounding is not retryable")
    if assistant_message.parent_id is None:
        raise HTTPException(status_code=400, detail="Assistant message has no user parent")
    user_message = await session.get(Message, assistant_message.parent_id)
    if user_message is None or user_message.role != "user":
        raise HTTPException(status_code=400, detail="Assistant message has no user parent")

    tool_sources_used = await get_tool_sources_used_for_message(session, assistant_message.id)
    grounding_source_candidates = with_canned_response_source_candidate(tool_sources_used)

    await session.refresh(metadata, with_for_update=True)
    if effective_grounding_source_status(metadata) != GROUNDING_SOURCE_STATUS_FAILED:
        raise HTTPException(status_code=409, detail="Source grounding is not retryable")
    metadata.grounding_source_keys = None
    metadata.grounding_source_status = GROUNDING_SOURCE_STATUS_PENDING
    await session.commit()

    assistant_answer = (
        assistant_message.guardrails_blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE
        if assistant_message.guardrails_blocked
        else assistant_message.content
    )
    with otel_export_scope(enabled=True):
        grounding_task = asyncio.create_task(
            _select_and_store_grounding_sources_in_background(
                assistant_message_id=assistant_message.id,
                user_message_id=user_message.id,
                assistant_answer=assistant_answer,
                sources=grounding_source_candidates,
            )
        )
    _track_background_task(grounding_task)
    grounding_sources_used, grounding_source_status = await asyncio.shield(grounding_task)
    return GroundingSourcesResponse(
        assistant_message_id=assistant_message.id,
        grounding_sources_used=grounding_sources_used,
        grounding_source_status=grounding_source_status,
    )


@router.post("/messages/internal/stream", response_class=StreamingResponse)
async def send_internal_message_stream(
    request: ChatRequest, session: SessionDep, current_user: CurrentUser
) -> StreamingResponse:
    mark_current_span_for_otel_export()
    permission_map = await get_effective_permission_map(session, current_user)
    can_view_response_cost = permission_map.get(PermissionKey.CHAT_VIEW_RESPONSE_COST, False)
    can_view_guardrails_failures = permission_map.get(
        PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES, False
    )
    can_view_sources = permission_map.get(PermissionKey.CHAT_VIEW_SOURCES, False)
    can_view_tools = permission_map.get(PermissionKey.CHAT_VIEW_TOOLS, False)
    conversation_kind = request.conversation_kind
    parent_message_id = request.parent_message_id
    parent_message_was_provided = "parent_message_id" in request.model_fields_set
    draft_prompt_templates, prompt_context = _normalize_draft_prompt_templates(request)
    generation_attempt_id = request.generation_attempt_id or uuid4()
    request_fingerprint = generation_request_fingerprint(request)

    existing_attempt = await _get_generation_attempt_if_exists(
        session,
        generation_attempt_id=generation_attempt_id,
        current_user=current_user,
        request_fingerprint=request_fingerprint,
        permission_map=permission_map,
    )
    if existing_attempt is not None:
        _raise_existing_generation_attempt(existing_attempt)

    if conversation_kind == "investigation":
        _ensure_investigation_access(permission_map)
        if request.conversation_id is None:
            raise HTTPException(
                status_code=400,
                detail="Investigation messages require an existing investigation conversation",
            )

    is_new_conversation = request.conversation_id is None
    if is_new_conversation:
        if request.is_regeneration:
            raise HTTPException(
                status_code=400, detail="Regeneration requires an explicit parent message"
            )
        if parent_message_id is not None:
            raise HTTPException(
                status_code=400, detail="A new conversation cannot have a parent message"
            )
        conversation = Conversation(
            title=build_fallback_title(request.user_prompt),
            user=False,
            project="demo",
            user_id=current_user.id,
            is_public=False,
            kind=conversation_kind,
            prompt_source=(prompt_context.get("source") if prompt_context is not None else None),
            prompt_context=prompt_context,
        )
        session.add(conversation)
        await session.flush()
    else:
        assert request.conversation_id is not None
        conversation = await _get_stream_conversation_or_404(session, request.conversation_id)
        _ensure_conversation_author_access(conversation, current_user)
        _ensure_draft_context_is_allowed(conversation, prompt_context)
        if conversation.kind == "investigation":
            _ensure_investigation_access(permission_map)
            conversation_kind = "investigation"
        elif conversation_kind == "investigation":
            raise HTTPException(status_code=400, detail="Conversation is not an investigation")
        if request.is_regeneration and (
            not parent_message_was_provided or parent_message_id is None
        ):
            raise HTTPException(
                status_code=400, detail="Regeneration requires an explicit parent message"
            )
        if parent_message_id is None:
            if not parent_message_was_provided:
                path = await get_current_branch_path(session, request.conversation_id)
                if path:
                    parent_message_id = path[-1]
        else:
            parent_message = await session.get(Message, parent_message_id)
            if parent_message is None:
                raise HTTPException(status_code=404, detail="Parent message not found")
            if parent_message.conversation_id != request.conversation_id:
                raise HTTPException(
                    status_code=400, detail="Parent message is not in this conversation"
                )
            if request.is_regeneration and parent_message.role != "user":
                raise HTTPException(
                    status_code=400, detail="Regeneration parent must be a user message"
                )

    conversation_id = conversation.id
    conversation_title = conversation.title
    now = current_time_utc()
    inserted_attempt_id = await session.scalar(
        postgres_insert(ChatGenerationAttempt)
        .values(
            id=generation_attempt_id,
            user_id=current_user.id,
            conversation_id=conversation_id,
            request_fingerprint=request_fingerprint,
            status=_GENERATION_ATTEMPT_PENDING,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[ChatGenerationAttempt.id])
        .returning(ChatGenerationAttempt.id)
    )
    if inserted_attempt_id is None:
        await session.rollback()
        existing_attempt = await _get_generation_attempt_if_exists(
            session,
            generation_attempt_id=generation_attempt_id,
            current_user=current_user,
            request_fingerprint=request_fingerprint,
            permission_map=permission_map,
        )
        if existing_attempt is None:
            raise HTTPException(status_code=409, detail="Generation attempt conflict")
        _raise_existing_generation_attempt(existing_attempt)

    # The durable pending attempt and any new conversation shell commit before
    # provider waits, making an unknown stream outcome queryable.
    await session.commit()

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str, payload: dict[str, Any]) -> None:
        await queue.put(_format_sse_event(event, payload))

    async def worker() -> None:
        initial_title_task: asyncio.Task[None] | None = None
        transcript_title_task: asyncio.Task[None] | None = None
        grounding_task: (
            asyncio.Task[tuple[list[MessageSourceUsed], GroundingSourceResultStatus]] | None
        ) = None
        persisted_user_message_id: UUID | None = None
        persisted_assistant_message: Message | MessageOut | None = None
        assistant_message_emitted = False
        try:
            with otel_export_scope(enabled=True):
                chatbot_settings, guardrail_settings = _get_model_settings(
                    request, conversation_kind=conversation_kind
                )

                if is_new_conversation:
                    await emit(
                        "conversation",
                        {
                            "conversation_id": str(conversation_id),
                            "conversation_title": conversation_title,
                        },
                    )
                else:
                    await emit("conversation", {"conversation_id": str(conversation_id)})

                async def emit_title_update(title: str, stage: str) -> None:
                    await emit(
                        "title_update",
                        {"conversation_id": str(conversation_id), "title": title, "stage": stage},
                    )

                if is_new_conversation:
                    with otel_export_scope(enabled=False):
                        initial_title_task = asyncio.create_task(
                            _generate_initial_title(
                                conversation_id,
                                request.user_prompt,
                                is_internal=True,
                                on_title=lambda title: emit_title_update(title, "initial"),
                            )
                        )

                async def emit_agent_event(event: str, payload: dict[str, Any]) -> None:
                    await emit(event, {"conversation_id": str(conversation_id), **payload})

                with span_persistence_scope() as response_span_scope:
                    if conversation_kind == "investigation":
                        user_message_id, assistant_message_out = await handle_investigation_turn(
                            project_name="demo",
                            conversation_id=conversation_id,
                            parent_message_id=parent_message_id,
                            user_prompt=request.user_prompt,
                            chatbot_model_settings=chatbot_settings,
                            is_regeneration=request.is_regeneration,
                            user_id=current_user.id,
                            session=session,
                            tool_session_factory=async_session_factory,
                            prompt_set_version_id=request.prompt_set_version_id,
                            event_emitter=emit_agent_event,
                        )
                    else:
                        user_message_id, assistant_message_out = await handle_conversation_turn(
                            project_name="demo",
                            conversation_id=conversation_id,
                            parent_message_id=parent_message_id,
                            user_prompt=request.user_prompt,
                            chatbot_model_settings=chatbot_settings,
                            guardrail_model_settings=guardrail_settings,
                            is_regeneration=request.is_regeneration,
                            is_internal=True,
                            enable_guardrails=settings.ENABLE_GUARDRAILS,
                            max_guardrails_retries=settings.MAX_GUARDRAILS_RETRIES,
                            user_id=current_user.id,
                            session=session,
                            tool_session_factory=async_session_factory,
                            prompt_set_version_id=request.prompt_set_version_id,
                            prompt_template_overrides=draft_prompt_templates,
                            prompt_context=prompt_context,
                            event_emitter=emit_agent_event,
                        )

                assert assistant_message_out.conversation_id is not None

                conversation = await _get_stream_conversation_or_404(
                    session, assistant_message_out.conversation_id
                )
                if prompt_context is not None and conversation.prompt_source == "draft":
                    conversation.prompt_context = prompt_context

                assistant_message = _visible_assistant_content(assistant_message_out)

                generation_attempt = _require_generation_attempt(
                    await session.get(ChatGenerationAttempt, generation_attempt_id)
                )
                generation_attempt.status = _GENERATION_ATTEMPT_COMPLETED
                generation_attempt.user_message_id = user_message_id
                generation_attempt.assistant_message_id = assistant_message_out.id
                await session.commit()
                persisted_user_message_id = user_message_id
                persisted_assistant_message = assistant_message_out
                await wait_for_pending_spans(scope=response_span_scope)
                response_metrics = await _get_message_response_diagnostics(
                    assistant_message_out.id,
                    include_cost=can_view_response_cost,
                    include_guardrails_failures=can_view_guardrails_failures,
                )
                await session.refresh(conversation)
                tool_sources_used = await get_tool_sources_used_for_message(
                    session, assistant_message_out.id
                )
                grounding_source_status = None
                grounding_sources_used: list[MessageSourceUsed] = []
                if conversation_kind != "investigation":
                    grounding_source_candidates = with_canned_response_source_candidate(
                        tool_sources_used
                    )
                    await mark_grounding_sources_pending(
                        session, assistant_message_id=assistant_message_out.id
                    )
                    await session.commit()
                    grounding_source_status = GROUNDING_SOURCE_STATUS_PENDING
                    grounding_task = asyncio.create_task(
                        _select_and_store_grounding_sources_in_background(
                            assistant_message_id=assistant_message_out.id,
                            user_message_id=user_message_id,
                            assistant_answer=assistant_message,
                            sources=grounding_source_candidates,
                        )
                    )
                    _track_background_task(grounding_task)

                await emit(
                    "assistant_message",
                    {
                        "conversation_id": str(conversation.id),
                        "user_message_id": str(user_message_id),
                        "assistant_message_id": str(assistant_message_out.id),
                        "assistant_message": assistant_message,
                        "guardrails_blocked": assistant_message_out.guardrails_blocked,
                        "guardrails_blocked_message": (
                            assistant_message_out.guardrails_blocked_message
                        ),
                        "guardrails_failures": response_metrics["guardrails_failures"],
                        "parent_message_id": (
                            str(assistant_message_out.parent_id)
                            if assistant_message_out.parent_id is not None
                            else None
                        ),
                        "generation_time_ms": (
                            round(assistant_message_out.metadata.total_time * 1000)
                            if assistant_message_out.metadata is not None
                            and assistant_message_out.metadata.total_time is not None
                            else None
                        ),
                        "generation_timing": _build_generation_timing_payload(
                            assistant_message_out
                        ),
                        "response_cost": response_metrics["response_cost"],
                        "response_usage": response_metrics["response_usage"],
                        "response_cost_breakdown": response_metrics["response_cost_breakdown"],
                        "tool_sources_used": [
                            source.model_dump(mode="json") for source in tool_sources_used
                        ]
                        if can_view_tools
                        else [],
                        "grounding_sources_used": [
                            source.model_dump(mode="json") for source in grounding_sources_used
                        ]
                        if can_view_sources
                        else [],
                        "grounding_source_status": (
                            grounding_source_status if can_view_sources else None
                        ),
                    },
                )
                assistant_message_emitted = True

                with otel_export_scope(enabled=False):
                    summary_task = asyncio.create_task(
                        summarize_internal_conversation(conversation.id)
                    )
                _track_background_task(summary_task)

                if is_new_conversation:
                    with otel_export_scope(enabled=False):
                        transcript_title_task = asyncio.create_task(
                            _generate_transcript_title(
                                conversation.id,
                                request.user_prompt,
                                assistant_message,
                                assistant_message_id=assistant_message_out.id,
                                is_internal=True,
                                on_title=lambda title: emit_title_update(title, "post_assistant"),
                            )
                        )

                if grounding_task is not None:
                    grounding_sources_used, grounding_source_status = await asyncio.shield(
                        grounding_task
                    )
                    if can_view_sources:
                        await emit(
                            "grounding_sources",
                            {
                                "conversation_id": str(conversation.id),
                                "assistant_message_id": str(assistant_message_out.id),
                                "grounding_sources_used": [
                                    source.model_dump(mode="json")
                                    for source in grounding_sources_used
                                ],
                                "grounding_source_status": grounding_source_status,
                            },
                        )

                if initial_title_task is not None:
                    await initial_title_task
                if transcript_title_task is not None:
                    await transcript_title_task
        except asyncio.CancelledError:
            await session.rollback()
            await _finalize_failed_generation_attempt(
                session, generation_attempt_id=generation_attempt_id
            )
            raise
        except Exception:
            failure_retryable = False
            if persisted_assistant_message is None:
                with suppress(Exception):
                    await session.rollback()
                generation_attempt = await _finalize_failed_generation_attempt(
                    session, generation_attempt_id=generation_attempt_id
                )
                failure_retryable = (
                    generation_attempt is not None
                    and generation_attempt.status == _GENERATION_ATTEMPT_FAILED
                )
                if (
                    generation_attempt is not None
                    and generation_attempt.status == _GENERATION_ATTEMPT_COMPLETED
                    and generation_attempt.user_message_id is not None
                    and generation_attempt.assistant_message_id is not None
                ):
                    recovered_message = await session.get(
                        Message, generation_attempt.assistant_message_id
                    )
                    if recovered_message is not None:
                        persisted_user_message_id = generation_attempt.user_message_id
                        persisted_assistant_message = recovered_message
            else:
                with suppress(Exception):
                    await session.commit()

            if persisted_assistant_message is None:
                logger.exception(
                    "Internal message generation failed for attempt %s", generation_attempt_id
                )
            else:
                logger.exception(
                    "Internal message post-processing failed for completed attempt %s",
                    generation_attempt_id,
                )

            if persisted_assistant_message is not None and not assistant_message_emitted:
                assert persisted_user_message_id is not None
                await emit(
                    "assistant_message",
                    _minimal_assistant_payload(
                        user_message_id=persisted_user_message_id,
                        assistant_message=persisted_assistant_message,
                    ),
                )
                assistant_message_emitted = True
            elif not assistant_message_emitted:
                await emit(
                    "error",
                    {
                        "code": "message_generation_failed",
                        "message": _MESSAGE_GENERATION_FAILED_MESSAGE,
                        "retryable": failure_retryable,
                    },
                )
        finally:
            await queue.put(None)

    worker_task = asyncio.create_task(worker())

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not worker_task.done():
                worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
