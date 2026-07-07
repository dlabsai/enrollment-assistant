import asyncio
import json
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, false, func, literal_column, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import CurrentUser, SessionDep
from app.api.grounding_agent import (
    GROUNDING_SOURCE_STATUS_PENDING,
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
from app.chat.engine import ModelSettings, handle_conversation_turn, handle_investigation_turn
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
from app.models import AssistantMessageMetadata, Conversation, Message, OtelSpan, RbacGroup, User
from app.otel import mark_current_span_for_otel_export, otel_export_scope, wait_for_pending_spans
from app.utils import logger

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


def _format_sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


class ChatRequest(BaseModel):
    user_prompt: str
    conversation_id: UUID | None = None
    parent_message_id: UUID | None = None
    prompt_set_version_id: UUID | None = None
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
    output_tokens: int | None = None
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


def _ensure_internal_access(conversation: Conversation, current_user: CurrentUser) -> None:
    if conversation.is_public:
        raise HTTPException(status_code=403, detail="Access denied")

    if conversation.user_id == current_user.id or current_user.group.slug in {"admin", "dev"}:
        return

    raise HTTPException(status_code=403, detail="Access denied")


async def _get_stream_conversation_or_404(
    session: SessionDep | Any, conversation_id: UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _get_model_settings(request: ChatRequest) -> tuple[ModelSettings, ModelSettings]:
    is_investigation = request.conversation_kind == "investigation"
    investigation_reasoning_effort: ReasoningEffort = settings.INVESTIGATION_REASONING_EFFORT
    chatbot = ModelSettings(
        model=request.chatbot_model
        or (settings.INVESTIGATION_MODEL if is_investigation else settings.CHATBOT_MODEL),
        temperature=settings.CHATBOT_MODEL_TEMPERATURE or None,
        max_tokens=settings.CHATBOT_MODEL_MAX_TOKENS or None,
        reasoning_effort=request.chatbot_reasoning_effort
        or (investigation_reasoning_effort if is_investigation else None),
    )
    guardrail = ModelSettings(
        model=request.guardrail_model or settings.GUARDRAIL_MODEL,
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE or None,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS or None,
        reasoning_effort=request.guardrail_reasoning_effort,
    )
    return chatbot, guardrail


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
    internal_visibility_condition = _internal_visibility_condition(
        current_user, permission_map=permission_map
    )

    owner_user_alias = aliased(User)
    conversation_user_name = owner_user_alias.name.label("conversation_user_name")
    conversation_user_email = owner_user_alias.email.label("conversation_user_email")
    content_length = func.char_length(Message.content).label("content_length")
    generation_time_ms = (AssistantMessageMetadata.total_time * 1000).label("generation_time_ms")
    latest_trace_span_alias = aliased(OtelSpan)
    latest_span_alias = aliased(OtelSpan)
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
    trace_id = (
        select(latest_span_alias.trace_id)
        .where(latest_span_alias.message_id == Message.id)
        .order_by(
            latest_span_alias.start_time.desc().nullslast(), latest_span_alias.created_at.desc()
        )
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    ).label("trace_id")
    span_id = (
        select(latest_span_alias.span_id)
        .where(latest_span_alias.message_id == Message.id)
        .order_by(
            latest_span_alias.start_time.desc().nullslast(), latest_span_alias.created_at.desc()
        )
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    ).label("span_id")

    base_stmt = (
        select(
            Message,
            Conversation,
            content_length,
            conversation_user_name,
            conversation_user_email,
            generation_time_ms,
            input_tokens,
            output_tokens,
            tool_call_count,
            guardrail_failure_count,
            trace_id,
            span_id,
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

    total_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await session.execute(total_stmt)).scalar() or 0

    sort_map: dict[str, Any] = {
        "content_length": content_length,
        "created_at": Message.created_at,
        "updated_at": Message.updated_at,
        "role": Message.role,
        "conversation_title": Conversation.title,
        "generation_time_ms": generation_time_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_call_count": tool_call_count,
        "guardrail_failure_count": guardrail_failure_count,
        "guardrails_blocked": Message.guardrails_blocked,
    }
    sort_column = sort_map.get(sort_by, Message.created_at)
    sort_expression = sort_column.desc() if descending else sort_column.asc()
    if sort_by in {"input_tokens", "output_tokens"}:
        sort_expression = sort_expression.nullslast()
    stmt = base_stmt.order_by(sort_expression).offset(offset).limit(limit)

    rows = (await session.execute(stmt)).all()
    return MessageListPage(
        total=total,
        items=[
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
                generation_time_ms=round(generation_time_ms_value)
                if generation_time_ms_value is not None
                else None,
                input_tokens=input_tokens_value,
                output_tokens=output_tokens_value,
                tool_call_count=tool_call_count_value,
                guardrail_failure_count=guardrail_failure_count_value,
                guardrails_blocked=message.guardrails_blocked,
                trace_id=trace_id_value,
                span_id=span_id_value,
                created_at=message.created_at,
                updated_at=message.updated_at,
            )
            for (
                message,
                conversation,
                content_length_value,
                conversation_user_name_value,
                conversation_user_email_value,
                generation_time_ms_value,
                input_tokens_value,
                output_tokens_value,
                tool_call_count_value,
                guardrail_failure_count_value,
                trace_id_value,
                span_id_value,
            ) in rows
        ],
    )


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
    is_internal: bool,
    on_title: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    role_label = "Staff" if is_internal else "User"
    transcript = f"{role_label}: {user_prompt}\n\nAssistant: {assistant_message}"
    fallback = build_fallback_title(user_prompt)
    title = await generate_conversation_title_from_transcript(
        transcript, conversation_id=conversation_id, is_internal=is_internal, fallback=fallback
    )
    await _persist_conversation_title(conversation_id, title)
    if on_title is not None:
        await on_title(title)


async def _select_and_store_grounding_sources_in_background(
    *,
    assistant_message_id: UUID,
    user_message_id: UUID,
    assistant_answer: str,
    sources: list[MessageSourceUsed],
) -> tuple[list[MessageSourceUsed], str]:
    async with get_session() as grounding_session:
        selected_keys, status = await select_and_store_grounding_sources(
            grounding_session,
            assistant_message_id=assistant_message_id,
            user_message_id=user_message_id,
            assistant_answer=assistant_answer,
            sources=sources,
        )
    return filter_sources_by_keys(sources, selected_keys), status


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

    if request.conversation_kind == "investigation":
        _ensure_investigation_access(permission_map)
        if request.conversation_id is None:
            raise HTTPException(
                status_code=400,
                detail="Investigation messages require an existing investigation conversation",
            )

    if request.conversation_id is not None:
        conversation = await _get_stream_conversation_or_404(session, request.conversation_id)
        _ensure_internal_access(conversation, current_user)
        if conversation.kind == "investigation":
            _ensure_investigation_access(permission_map)
            if conversation.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            request.conversation_kind = "investigation"
        elif request.conversation_kind == "investigation":
            raise HTTPException(status_code=400, detail="Conversation is not an investigation")
        if request.parent_message_id is None:
            path = await get_current_branch_path(session, request.conversation_id)
            if path:
                request.parent_message_id = path[-1]

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str, payload: dict[str, Any]) -> None:
        await queue.put(_format_sse_event(event, payload))

    async def worker() -> None:
        initial_title_task: asyncio.Task[None] | None = None
        transcript_title_task: asyncio.Task[None] | None = None
        grounding_task: asyncio.Task[tuple[list[MessageSourceUsed], str]] | None = None
        try:
            with otel_export_scope(enabled=True):
                chatbot_settings, guardrail_settings = _get_model_settings(request)

                conversation_id = request.conversation_id
                is_new_conversation = conversation_id is None

                if is_new_conversation:
                    title = build_fallback_title(request.user_prompt)
                    conversation = Conversation(
                        title=title,
                        user=False,
                        project="demo",
                        user_id=current_user.id,
                        is_public=False,
                        kind=request.conversation_kind,
                    )
                    session.add(conversation)
                    await session.flush()
                    conversation_id = conversation.id
                    await session.commit()
                    await session.refresh(conversation)

                    await emit(
                        "conversation",
                        {
                            "conversation_id": str(conversation_id),
                            "conversation_title": conversation.title,
                        },
                    )
                else:
                    assert conversation_id is not None
                    await emit("conversation", {"conversation_id": str(conversation_id)})

                async def emit_title_update(title: str, stage: str) -> None:
                    await emit(
                        "title_update",
                        {"conversation_id": str(conversation_id), "title": title, "stage": stage},
                    )

                if is_new_conversation:
                    assert conversation_id is not None
                    with otel_export_scope(enabled=False):
                        initial_title_task = asyncio.create_task(
                            _generate_initial_title(
                                conversation_id,
                                request.user_prompt,
                                is_internal=True,
                                on_title=lambda title: emit_title_update(title, "initial"),
                            )
                        )

                assert conversation_id is not None

                async def emit_agent_event(event: str, payload: dict[str, Any]) -> None:
                    await emit(event, {"conversation_id": str(conversation_id), **payload})

                if request.conversation_kind == "investigation":
                    user_message_id, assistant_message_out = await handle_investigation_turn(
                        project_name="demo",
                        conversation_id=conversation_id,
                        parent_message_id=request.parent_message_id,
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
                        parent_message_id=request.parent_message_id,
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
                        event_emitter=emit_agent_event,
                    )

                assert assistant_message_out.conversation_id is not None

                conversation = await _get_stream_conversation_or_404(
                    session, assistant_message_out.conversation_id
                )

                assistant_message = (
                    assistant_message_out.guardrails_blocked_message
                    or settings.GUARDRAILS_BLOCKED_MESSAGE
                    if assistant_message_out.guardrails_blocked
                    else assistant_message_out.content
                )

                await session.commit()
                await session.refresh(conversation)
                await wait_for_pending_spans()
                response_metrics = await _get_message_response_diagnostics(
                    assistant_message_out.id,
                    include_cost=can_view_response_cost,
                    include_guardrails_failures=can_view_guardrails_failures,
                )
                tool_sources_used = await get_tool_sources_used_for_message(
                    session, assistant_message_out.id
                )
                grounding_source_status = None
                grounding_sources_used: list[MessageSourceUsed] = []
                if request.conversation_kind != "investigation":
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
        except Exception as exc:
            logger.exception("Failed to stream internal message")
            await emit("error", {"message": str(exc)})
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
