from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from typing import Annotated, Any, Literal
from typing import cast as type_cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import (
    Float,
    String,
    and_,
    case,
    cast,
    delete,
    desc,
    false,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, SessionDep
from app.api.guardrails_failures import (
    GUARDRAILS_AGENT_NAMES,
    GUARDRAILS_URL_SPAN_NAME,
    GuardrailsFailureOut,
    GuardrailsTraceSpan,
    guardrails_failures_from_spans,
)
from app.api.message_sources import (
    MessageSourceUsed,
    filter_sources_by_keys,
    get_tool_sources_used_by_message_ids,
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
from app.api.schemas import PaginationParams
from app.chat.engine import Feedback, MessageOut
from app.chat.title import build_fallback_title, generate_conversation_title_from_transcript
from app.chat.tree_utils import (
    get_conversation_path,
    get_current_branch_path,
    get_message_children,
    update_active_child_for_branch_switch,
)
from app.core.config import settings
from app.core.rbac import (
    PermissionKey,
    can_view_chat_owner,
    get_allowed_chat_owner_group_slugs,
    get_effective_permission_map,
)
from app.models import (
    AssistantMessageMetadata,
    Conversation,
    ConversationFeedback,
    Message,
    MessageFeedback,
    OtelSpan,
    PublicChatContact,
    RbacGroup,
    User,
)
from app.models import Rating as MessageRating

router = APIRouter(prefix="/conversations", tags=["conversations"])

_PREVIEW_MAX_LENGTH = 60
_CHATBOT_TIMING_AGENT_NAMES = ("chatbot", "investigation")


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    summary: str | None = None
    last_message_preview: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    is_public: bool = False
    user_name: str | None = None
    user_email: str | None = None


class ConversationMessage(BaseModel):
    id: UUID
    role: str
    content: str
    parent_id: UUID | None
    created_at: datetime
    guardrails_blocked: bool = False
    guardrails_blocked_message: str | None = None


class ConversationMessageFeedback(BaseModel):
    id: UUID
    rating: MessageRating
    text: str | None = None
    user_id: UUID
    user_name: str
    is_current_user: bool
    created_at: datetime
    updated_at: datetime


class ConversationMessageGenerationTiming(BaseModel):
    total_time_ms: int | None = None
    chatbot_time_ms: int | None = None
    guardrail_time_ms: int | None = None
    chatbot_times_ms: list[int] | None = None
    guardrail_times_ms: list[int] | None = None
    chatbot_model: str | None = None
    guardrail_model: str | None = None


class ConversationMessageResponseUsage(BaseModel):
    input_tokens: int | None = None
    uncached_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None


class ConversationMessageResponseCostBreakdown(BaseModel):
    input_cost: float | None = None
    cache_read_input_cost: float | None = None
    output_cost: float | None = None


@dataclass(frozen=True)
class _TraceGenerationTiming:
    chatbot_time: float | None
    chatbot_model: str | None


class ConversationMessageWithFeedback(ConversationMessage):
    feedback: list[ConversationMessageFeedback] = []
    assistant_tool_calls: list[dict[str, Any]] | None = None
    tool_sources_used: list[MessageSourceUsed] = []
    grounding_sources_used: list[MessageSourceUsed] = []
    grounding_source_status: str | None = None
    generation_time_ms: int | None = None
    generation_timing: ConversationMessageGenerationTiming | None = None
    response_cost: float | None = None
    response_usage: ConversationMessageResponseUsage | None = None
    response_cost_breakdown: ConversationMessageResponseCostBreakdown | None = None
    guardrails_failures: list[GuardrailsFailureOut] | None = None


class ConversationDetail(BaseModel):
    id: UUID
    title: str | None
    summary: str | None = None
    messages: list[ConversationMessageWithFeedback]
    investigation_source_conversation_id: UUID | None = None
    investigation_source_message_id: UUID | None = None
    investigation_source_feedback_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    is_public: bool = False
    user_name: str | None = None
    user_email: str | None = None


class ConversationListItem(BaseModel):
    id: UUID
    title: str | None
    summary: str | None = None
    last_message_preview: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    is_public: bool = False
    user_name: str | None = None
    user_email: str | None = None
    total_cost: float | None = None
    feedback_up: int = 0
    feedback_down: int = 0


class ConversationListPage(BaseModel):
    items: list[ConversationListItem]
    total: int


class ConversationUserOption(BaseModel):
    name: str | None = None
    email: str
    platform: Literal["internal", "public"]


class ConversationTitleUpdate(BaseModel):
    title: str


class ConversationTitleOut(BaseModel):
    title: str


class InvestigationCreateIn(BaseModel):
    conversation_id: UUID
    message_id: UUID
    feedback_id: UUID | None = None


class InvestigationCreateOut(BaseModel):
    conversation_id: UUID


class ConversationSearchResult(BaseModel):
    id: UUID
    title: str | None
    snippet: str
    updated_at: datetime


class FeedbackIn(BaseModel):
    rating: MessageRating
    text: str | None = None


class FeedbackOut(BaseModel):
    id: UUID
    rating: MessageRating
    text: str | None = None
    user_id: UUID
    user_name: str
    is_current_user: bool
    created_at: datetime
    updated_at: datetime


class MessageTreeNodeOut(BaseModel):
    message: MessageOut
    message_tree_nodes: list[MessageTreeNodeOut] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


class ConversationTreeOut(BaseModel):
    message_tree_nodes: dict[UUID, MessageTreeNodeOut] = Field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]
    current_branch_path: list[UUID] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    subtree_active_paths: dict[UUID, list[UUID]] = Field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]


class ConversationDetailTreeOut(BaseModel):
    id: UUID
    title: str | None
    user: bool
    conversation_tree: ConversationTreeOut
    created_at: datetime
    updated_at: datetime


class UpdateActiveChildIn(BaseModel):
    active_child_id: str | None


def _format_message_preview(content: str) -> str:
    if len(content) > _PREVIEW_MAX_LENGTH:
        return content[:_PREVIEW_MAX_LENGTH] + "..."
    return content


def _blocked_display_message(*, blocked: bool | None, blocked_message: str | None) -> str | None:
    if blocked is not True:
        return None
    return blocked_message or settings.GUARDRAILS_BLOCKED_MESSAGE


def _message_preview_content(
    *,
    role: str | None,
    content: str | None,
    guardrails_blocked: bool | None,
    guardrails_blocked_message: str | None,
) -> str | None:
    if content is None:
        return None
    if role == "assistant":
        blocked_message = _blocked_display_message(
            blocked=guardrails_blocked, blocked_message=guardrails_blocked_message
        )
        if blocked_message is not None:
            return blocked_message
    return content


def _build_search_snippet(content: str) -> str:
    return content


def _seconds_to_ms(value: float | None) -> int | None:
    return round(value * 1000) if value is not None else None


def _seconds_list_to_ms(values: list[float] | None) -> list[int] | None:
    return [round(value * 1000) for value in values] if values else None


def _get_model_name(model_settings: dict[str, Any] | None) -> str | None:
    model = model_settings.get("model") if model_settings is not None else None
    return model if isinstance(model, str) and model.strip() != "" else None


async def _get_generation_timing_by_message_id(
    session: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, _TraceGenerationTiming]:
    if not message_ids:
        return {}

    trace_rows = (
        await session.execute(
            select(OtelSpan.message_id, OtelSpan.trace_id)
            .where(OtelSpan.message_id.in_(message_ids))
            .where(OtelSpan.trace_id.is_not(None))
            .distinct()
        )
    ).all()
    trace_to_message_id = {
        trace_id: message_id
        for message_id, trace_id in trace_rows
        if message_id is not None and trace_id is not None
    }
    if not trace_to_message_id:
        return {}

    agent_name = func.jsonb_extract_path_text(OtelSpan.attributes, "gen_ai.agent.name")
    span_rows = (
        await session.execute(
            select(
                OtelSpan.trace_id,
                OtelSpan.request_model,
                OtelSpan.duration_ms,
                OtelSpan.start_time,
                OtelSpan.created_at,
            )
            .where(OtelSpan.trace_id.in_(list(trace_to_message_id)))
            .where(agent_name.in_(_CHATBOT_TIMING_AGENT_NAMES))
            .order_by(OtelSpan.start_time.asc().nullslast(), OtelSpan.created_at.asc())
        )
    ).all()

    spans_by_trace_id: dict[str, list[Any]] = {}
    for row in span_rows:
        spans_by_trace_id.setdefault(row.trace_id, []).append(row)

    timing_with_latest: dict[UUID, tuple[datetime, _TraceGenerationTiming]] = {}
    for trace_id, spans in spans_by_trace_id.items():
        message_id = trace_to_message_id.get(trace_id)
        if message_id is None:
            continue

        duration_values = [span.duration_ms for span in spans if span.duration_ms is not None]
        duration_seconds = sum(duration_values) / 1000 if duration_values else None
        model = next(
            (
                span.request_model
                for span in spans
                if isinstance(span.request_model, str) and span.request_model.strip() != ""
            ),
            None,
        )
        latest_at = max(span.start_time or span.created_at for span in spans)
        current = timing_with_latest.get(message_id)
        if current is None or latest_at > current[0]:
            timing_with_latest[message_id] = (
                latest_at,
                _TraceGenerationTiming(chatbot_time=duration_seconds, chatbot_model=model),
            )

    return {message_id: timing for message_id, (_latest, timing) in timing_with_latest.items()}


def _build_generation_timing(
    metadata: AssistantMessageMetadata | None, trace_timing: _TraceGenerationTiming | None
) -> ConversationMessageGenerationTiming | None:
    if metadata is None:
        return None

    chatbot_times_ms = _seconds_list_to_ms(metadata.chatbot_times)
    guardrail_times_ms = _seconds_list_to_ms(metadata.guardrail_times)
    chatbot_time_ms = (
        sum(chatbot_times_ms)
        if chatbot_times_ms is not None and len(chatbot_times_ms) > 1
        else _seconds_to_ms(trace_timing.chatbot_time if trace_timing is not None else None)
    )

    timing = ConversationMessageGenerationTiming(
        total_time_ms=_seconds_to_ms(metadata.total_time),
        chatbot_time_ms=chatbot_time_ms,
        guardrail_time_ms=_seconds_to_ms(metadata.guardrail_time),
        chatbot_times_ms=chatbot_times_ms,
        guardrail_times_ms=guardrail_times_ms,
        chatbot_model=trace_timing.chatbot_model if trace_timing is not None else None,
        guardrail_model=_get_model_name(metadata.guardrail_model_settings),
    )

    if all(value is None for value in timing.model_dump().values()):
        return None

    return timing


def _guardrails_trace_span_condition() -> Any:
    return or_(
        OtelSpan.name == GUARDRAILS_URL_SPAN_NAME,
        func.jsonb_extract_path_text(OtelSpan.attributes, "gen_ai.agent.name").in_(
            GUARDRAILS_AGENT_NAMES
        ),
    )


def _usage_or_none(
    *, input_tokens: int | None, cache_read_input_tokens: int | None, output_tokens: int | None
) -> ConversationMessageResponseUsage | None:
    if input_tokens is None and cache_read_input_tokens is None and output_tokens is None:
        return None
    return ConversationMessageResponseUsage(
        input_tokens=input_tokens,
        uncached_input_tokens=uncached_input_tokens(input_tokens, cache_read_input_tokens),
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
    )


def _is_admin_user(current_user: CurrentUser) -> bool:
    return current_user.group.slug in {"admin", "dev"}


def _ensure_public_access(current_user: CurrentUser) -> None:
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied")


def _ensure_investigation_access(permission_map: dict[PermissionKey, bool]) -> None:
    if not permission_map.get(PermissionKey.ACCESS_INVESTIGATIONS, False):
        raise HTTPException(status_code=403, detail="Access denied")


def _ensure_conversation_access(conversation: Conversation, current_user: CurrentUser) -> None:
    if conversation.is_public:
        _ensure_public_access(current_user)
        return

    if conversation.user_id == current_user.id:
        return

    raise HTTPException(status_code=403, detail="Access denied")


async def _ensure_internal_conversation_access(
    session: AsyncSession, conversation: Conversation, current_user: CurrentUser
) -> None:
    _ensure_conversation_access(conversation, current_user)
    if conversation.kind == "investigation":
        permission_map = await get_effective_permission_map(session, current_user)
        _ensure_investigation_access(permission_map)


async def _ensure_conversation_access_for_source(
    session: AsyncSession,
    conversation: Conversation,
    current_user: CurrentUser,
    source: Literal["chat", "chats", "messages", "investigate", "investigations"],
) -> None:
    if conversation.kind == "investigation":
        permission_map = await get_effective_permission_map(session, current_user)
        _ensure_investigation_access(permission_map)
        if source == "investigate":
            if conversation.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            return
        if source == "investigations":
            owner_group_slug = await _get_conversation_owner_group_slug(
                session, conversation, current_user
            )
            if not can_view_chat_owner(
                permission_map=permission_map,
                owner_group_slug=owner_group_slug,
                is_owner=conversation.user_id == current_user.id,
            ):
                raise HTTPException(status_code=403, detail="Access denied")
            return
        raise HTTPException(status_code=403, detail="Access denied")

    if source in {"investigate", "investigations"}:
        raise HTTPException(status_code=403, detail="Access denied")

    if source == "chat":
        _ensure_conversation_access(conversation, current_user)
        return

    permission_map = await get_effective_permission_map(session, current_user)
    required_permission = (
        PermissionKey.ACCESS_MESSAGES if source == "messages" else PermissionKey.ACCESS_CHATS
    )
    if not permission_map.get(required_permission, False):
        raise HTTPException(status_code=403, detail="Access denied")

    if conversation.is_public:
        _ensure_public_access(current_user)
        return

    owner_group_slug = await _get_conversation_owner_group_slug(session, conversation, current_user)
    if not can_view_chat_owner(
        permission_map=permission_map,
        owner_group_slug=owner_group_slug,
        is_owner=conversation.user_id == current_user.id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")


async def _get_conversation_or_404(session: AsyncSession, conversation_id: UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def _get_message_or_404(session: AsyncSession, message_id: UUID) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


async def _get_conversation_path_through_message(
    session: AsyncSession, target_message_id: UUID
) -> list[UUID]:
    """Return the branch containing the target message, extended to its active leaf."""
    target_path = await get_conversation_path(session, target_message_id)
    path_ids = [message.id for message in target_path]
    current_message = target_path[-1] if target_path else None

    while current_message is not None:
        children = await get_message_children(session, current_message.id)
        if not children:
            break
        if len(children) == 1:
            current_message = children[0]
        elif current_message.active_child_id is not None:
            current_message = await session.get(Message, current_message.active_child_id)
        else:
            current_message = children[0]

        if current_message is not None:
            path_ids.append(current_message.id)

    return path_ids


async def _get_message_feedback_or_404(session: AsyncSession, feedback_id: UUID) -> MessageFeedback:
    stmt = (
        select(MessageFeedback)
        .options(joinedload(MessageFeedback.user))
        .where(MessageFeedback.id == feedback_id)
    )
    feedback = (await session.execute(stmt)).scalar_one_or_none()
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_conversation_search_conditions(search: str, *, phrase_search: bool = True) -> list[Any]:
    terms = [search] if phrase_search else search.split()
    terms = [term for term in terms if term != ""]
    if not terms:
        return []

    def term_conditions(term: str) -> list[Any]:
        pattern = f"%{_escape_like(term)}%"
        message_match = (
            select(Message.id)
            .where(
                Message.conversation_id == Conversation.id,
                Message.content.ilike(pattern, escape="\\"),
            )
            .exists()
        )
        return [
            Conversation.title.ilike(pattern, escape="\\"),
            Conversation.summary.ilike(pattern, escape="\\"),
            message_match,
        ]

    if phrase_search:
        return term_conditions(terms[0])

    return [and_(*(or_(*term_conditions(term)) for term in terms))]


def _build_public_contact_search_conditions(
    search: str, *, phrase_search: bool = True
) -> list[Any]:
    terms = [search] if phrase_search else search.split()
    terms = [term for term in terms if term != ""]
    if not terms:
        return []

    def term_conditions(term: str) -> list[Any]:
        pattern = f"%{_escape_like(term)}%"
        return [
            PublicChatContact.first_name.ilike(pattern, escape="\\"),
            PublicChatContact.last_name.ilike(pattern, escape="\\"),
            PublicChatContact.email.ilike(pattern, escape="\\"),
        ]

    if phrase_search:
        return term_conditions(terms[0])

    return [and_(*(or_(*term_conditions(term)) for term in terms))]


def _get_platform_scope(current_user: CurrentUser, platform: str | None) -> tuple[bool, bool]:
    if platform is not None and platform not in {"internal", "public"}:
        raise HTTPException(status_code=400, detail="Invalid platform")

    can_view_public = _is_admin_user(current_user)
    if platform == "public" and not can_view_public:
        raise HTTPException(status_code=403, detail="Access denied")

    include_internal = platform in (None, "internal")
    include_public = can_view_public and platform in (None, "public")
    return include_internal, include_public


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


async def _get_conversation_owner_group_slug(
    session: AsyncSession, conversation: Conversation, current_user: CurrentUser
) -> str | None:
    if conversation.user_id is None:
        return None

    if conversation.user_id == current_user.id:
        return current_user.group.slug

    return await session.scalar(
        select(RbacGroup.slug)
        .join(User, User.group_id == RbacGroup.id)
        .where(User.id == conversation.user_id)
    )


def _build_transcript(messages: list[Message], *, is_internal: bool) -> str:
    role_label = "Staff" if is_internal else "User"
    lines: list[str] = []
    for message in messages:
        role = role_label if message.role == "user" else "Assistant"
        lines.append(f"{role}: {message.content}")
    return "\n\n".join(lines)


async def _build_feedback_out(feedback: MessageFeedback, current_user: CurrentUser) -> FeedbackOut:
    return FeedbackOut(
        id=feedback.id,
        rating=feedback.rating,
        text=feedback.text,
        user_id=feedback.user_id,
        user_name=feedback.user.name,
        is_current_user=feedback.user_id == current_user.id,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


@router.get("", response_model=list[ConversationSummary], response_model_exclude_none=True)
async def list_internal_conversations(
    session: SessionDep,
    current_user: CurrentUser,
    kind: Annotated[Literal["chat", "investigation"], Query()] = "chat",
) -> Any:
    if kind == "investigation":
        permission_map = await get_effective_permission_map(session, current_user)
        _ensure_investigation_access(permission_map)

    last_message_subquery = select(
        Message.conversation_id,
        Message.role,
        Message.content,
        Message.guardrails_blocked,
        Message.guardrails_blocked_message,
        func.row_number()
        .over(partition_by=Message.conversation_id, order_by=desc(Message.created_at))
        .label("rn"),
    ).subquery()

    latest_message_time_subquery = (
        select(Message.conversation_id, func.max(Message.created_at).label("latest_message_time"))
        .group_by(Message.conversation_id)
        .subquery()
    )

    effective_updated_at = func.coalesce(
        latest_message_time_subquery.c.latest_message_time, Conversation.created_at
    ).label("effective_updated_at")

    stmt = (
        select(
            Conversation,
            func.count(Message.id).label("message_count"),
            last_message_subquery.c.role.label("last_message_role"),
            last_message_subquery.c.content.label("last_message_content"),
            last_message_subquery.c.guardrails_blocked.label("last_message_guardrails_blocked"),
            last_message_subquery.c.guardrails_blocked_message.label(
                "last_message_guardrails_blocked_message"
            ),
            effective_updated_at,
        )
        .outerjoin(Message, Conversation.id == Message.conversation_id)
        .outerjoin(
            last_message_subquery,
            (Conversation.id == last_message_subquery.c.conversation_id)
            & (last_message_subquery.c.rn == 1),
        )
        .outerjoin(
            latest_message_time_subquery,
            Conversation.id == latest_message_time_subquery.c.conversation_id,
        )
        .where(Conversation.is_public.is_(False))
        .where(Conversation.kind == kind)
        .where(Conversation.user_id == current_user.id)
        .group_by(
            Conversation.id,
            last_message_subquery.c.role,
            last_message_subquery.c.content,
            last_message_subquery.c.guardrails_blocked,
            last_message_subquery.c.guardrails_blocked_message,
            latest_message_time_subquery.c.latest_message_time,
        )
        .order_by(desc(effective_updated_at))
    )

    rows = (await session.execute(stmt)).all()

    return [
        ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            summary=conversation.summary,
            last_message_preview=(
                _format_message_preview(preview_content) if preview_content else None
            ),
            message_count=message_count,
            created_at=conversation.created_at,
            updated_at=updated_at,
            is_public=False,
        )
        for (
            conversation,
            message_count,
            last_role,
            last_content,
            last_guardrails_blocked,
            last_guardrails_blocked_message,
            updated_at,
        ) in rows
        for preview_content in [
            _message_preview_content(
                role=last_role,
                content=last_content,
                guardrails_blocked=last_guardrails_blocked,
                guardrails_blocked_message=last_guardrails_blocked_message,
            )
        ]
    ]


@router.get(
    "/search", response_model=list[ConversationSearchResult], response_model_exclude_none=True
)
async def search_internal_conversations(
    session: SessionDep,
    current_user: CurrentUser,
    search: Annotated[str, Query(min_length=1)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Any:
    search_term = search.strip()
    if search_term == "":
        return []

    pattern = f"%{search_term}%"

    latest_message_time_subquery = (
        select(Message.conversation_id, func.max(Message.created_at).label("latest_message_time"))
        .group_by(Message.conversation_id)
        .subquery()
    )

    def _message_match_subquery(column: Any) -> Any:
        return (
            select(column)
            .where(Message.conversation_id == Conversation.id, Message.content.ilike(pattern))
            .order_by(desc(Message.created_at))
            .limit(1)
            .scalar_subquery()
        )

    message_match_role_subquery = _message_match_subquery(Message.role)
    message_match_content_subquery = _message_match_subquery(Message.content)
    message_match_guardrails_blocked_subquery = _message_match_subquery(Message.guardrails_blocked)
    message_match_guardrails_blocked_message_subquery = _message_match_subquery(
        Message.guardrails_blocked_message
    )

    effective_updated_at = func.coalesce(
        latest_message_time_subquery.c.latest_message_time, Conversation.created_at
    ).label("effective_updated_at")

    stmt = (
        select(
            Conversation,
            message_match_role_subquery.label("message_match_role"),
            message_match_content_subquery.label("message_match_content"),
            message_match_guardrails_blocked_subquery.label("message_match_guardrails_blocked"),
            message_match_guardrails_blocked_message_subquery.label(
                "message_match_guardrails_blocked_message"
            ),
            effective_updated_at,
        )
        .outerjoin(
            latest_message_time_subquery,
            Conversation.id == latest_message_time_subquery.c.conversation_id,
        )
        .where(Conversation.is_public.is_(False))
        .where(Conversation.kind == "chat")
        .where(Conversation.user_id == current_user.id)
        .where(or_(*_build_conversation_search_conditions(search_term)))
        .order_by(desc(effective_updated_at))
        .offset(offset)
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()

    items: list[ConversationSearchResult] = []
    for (
        conversation,
        message_match_role,
        message_match_content,
        message_match_guardrails_blocked,
        message_match_guardrails_blocked_message,
        updated_at,
    ) in rows:
        message_candidate = _message_preview_content(
            role=message_match_role,
            content=message_match_content,
            guardrails_blocked=message_match_guardrails_blocked,
            guardrails_blocked_message=message_match_guardrails_blocked_message,
        )
        candidate = (message_candidate or "").strip()
        summary = (conversation.summary or "").strip()
        title = (conversation.title or "").strip()

        if candidate == "":
            if summary and search_term.lower() in summary.lower():
                candidate = summary
            elif title and search_term.lower() in title.lower():
                candidate = title
            elif summary:
                candidate = summary
            else:
                candidate = title

        items.append(
            ConversationSearchResult(
                id=conversation.id,
                title=conversation.title,
                snippet=_build_search_snippet(candidate),
                updated_at=updated_at,
            )
        )

    return items


@router.post("/investigations", response_model=InvestigationCreateOut)
async def create_investigation_conversation(
    request: InvestigationCreateIn, session: SessionDep, current_user: CurrentUser
) -> InvestigationCreateOut:
    permission_map = await get_effective_permission_map(session, current_user)
    _ensure_investigation_access(permission_map)

    source_conversation = await _get_conversation_or_404(session, request.conversation_id)
    await _ensure_conversation_access_for_source(
        session, source_conversation, current_user, "chats"
    )

    source_message = await _get_message_or_404(session, request.message_id)
    if source_message.conversation_id != source_conversation.id:
        raise HTTPException(status_code=400, detail="Message does not belong to conversation")
    if source_message.role != "assistant":
        raise HTTPException(
            status_code=400, detail="Investigation source must be an assistant response"
        )

    if request.feedback_id is not None:
        feedback = await _get_message_feedback_or_404(session, request.feedback_id)
        if feedback.message_id != source_message.id:
            raise HTTPException(status_code=400, detail="Feedback does not belong to message")

    title_seed = source_conversation.title or "Untitled chat"
    investigation = Conversation(
        title=f"Investigation: {title_seed}",
        user=False,
        project="demo",
        user_id=current_user.id,
        is_public=False,
        kind="investigation",
        investigation_source_conversation_id=source_conversation.id,
        investigation_source_message_id=source_message.id,
        investigation_source_feedback_id=request.feedback_id,
    )
    session.add(investigation)
    await session.commit()
    await session.refresh(investigation)
    return InvestigationCreateOut(conversation_id=investigation.id)


@router.get("/users", response_model=list[ConversationUserOption], response_model_exclude_none=True)
async def list_conversation_users(
    session: SessionDep,
    current_user: CurrentUser,
    search: Annotated[str | None, Query()] = None,
    platform: Annotated[str | None, Query()] = None,
    kind: Annotated[Literal["chat", "investigation"], Query()] = "chat",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    permission_map = await get_effective_permission_map(session, current_user)
    if kind == "investigation":
        _ensure_investigation_access(permission_map)
    elif not permission_map.get(PermissionKey.ACCESS_CHATS, False):
        raise HTTPException(status_code=403, detail="Access denied")

    if kind == "investigation" and platform == "public":
        raise HTTPException(status_code=400, detail="Investigations are internal only")

    include_internal, include_public = _get_platform_scope(current_user, platform)
    internal_visibility_condition = _internal_visibility_condition(
        current_user, permission_map=permission_map
    )
    pattern = f"%{search.strip()}%" if search is not None and search.strip() != "" else None

    statements: list[Any] = []

    if include_internal:
        internal_stmt = (
            select(
                User.name.label("name"),
                User.email.label("email"),
                literal("internal").label("platform"),
            )
            .join(Conversation, Conversation.user_id == User.id)
            .join(RbacGroup, User.group_id == RbacGroup.id)
            .where(Conversation.is_public.is_(False))
            .where(Conversation.kind == kind)
            .where(internal_visibility_condition)
        )
        if pattern is not None:
            internal_stmt = internal_stmt.where(
                or_(User.name.ilike(pattern), User.email.ilike(pattern))
            )
        statements.append(internal_stmt)

    if include_public:
        public_name = func.trim(
            func.concat(PublicChatContact.first_name, " ", PublicChatContact.last_name)
        )
        public_stmt = (
            select(
                public_name.label("name"),
                PublicChatContact.email.label("email"),
                literal("public").label("platform"),
            )
            .select_from(Conversation)
            .join(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
            .where(Conversation.is_public.is_(True))
            .where(Conversation.kind == kind)
            .where(PublicChatContact.email.is_not(None))
        )
        if pattern is not None:
            public_stmt = public_stmt.where(
                or_(
                    public_name.ilike(pattern),
                    PublicChatContact.first_name.ilike(pattern),
                    PublicChatContact.last_name.ilike(pattern),
                    PublicChatContact.email.ilike(pattern),
                )
            )
        statements.append(public_stmt)

    if not statements:
        return []

    combined = statements[0]
    for stmt in statements[1:]:
        combined = combined.union_all(stmt)

    subquery = combined.subquery()
    stmt = (
        select(subquery.c.name, subquery.c.email, subquery.c.platform)
        .distinct()
        .order_by(subquery.c.name.asc(), subquery.c.email.asc())
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()

    items: list[ConversationUserOption] = []
    for row in rows:
        name = row.name.strip() if isinstance(row.name, str) else None
        items.append(
            ConversationUserOption(name=name or None, email=row.email, platform=row.platform)
        )

    return items


@router.get("/paginated", response_model=ConversationListPage)
async def list_internal_conversations_paginated(
    session: SessionDep,
    current_user: CurrentUser,
    page_params: Annotated[PaginationParams, Depends()],
    search: Annotated[str | None, Query()] = None,
    platform: Annotated[str | None, Query()] = None,
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
    phrase_search: Annotated[bool, Query()] = False,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    kind: Annotated[Literal["chat", "investigation"], Query()] = "chat",
) -> Any:
    permission_map = await get_effective_permission_map(session, current_user)
    if kind == "investigation":
        _ensure_investigation_access(permission_map)
    elif not permission_map.get(PermissionKey.ACCESS_CHATS, False):
        raise HTTPException(status_code=403, detail="Access denied")

    if kind == "investigation" and platform == "public":
        raise HTTPException(status_code=400, detail="Investigations are internal only")

    include_internal, include_public = _get_platform_scope(current_user, platform)
    if kind == "investigation":
        include_public = False
    internal_visibility_condition = _internal_visibility_condition(
        current_user, permission_map=permission_map
    )

    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="Invalid time range")

    message_count_subquery = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    last_message_subquery = select(
        Message.conversation_id,
        Message.role,
        Message.content,
        Message.guardrails_blocked,
        Message.guardrails_blocked_message,
        func.row_number()
        .over(partition_by=Message.conversation_id, order_by=desc(Message.created_at))
        .label("rn"),
    ).subquery()

    latest_message_time_subquery = (
        select(Message.conversation_id, func.max(Message.created_at).label("latest_message_time"))
        .group_by(Message.conversation_id)
        .subquery()
    )

    def _build_cost_subquery(conversation_ids: list[UUID] | None = None) -> Any:
        trace_context_subquery = (
            select(
                OtelSpan.trace_id.label("trace_id"),
                func.max(cast(OtelSpan.conversation_id, String)).label("conversation_id"),
            )
            .where(OtelSpan.conversation_id.is_not(None))
            .group_by(OtelSpan.trace_id)
            .subquery()
        )

        conversation_id_expr = func.coalesce(
            OtelSpan.conversation_id, cast(trace_context_subquery.c.conversation_id, PGUUID)
        )
        stmt = (
            select(
                conversation_id_expr.label("conversation_id"),
                func.sum(OtelSpan.total_cost).label("total_cost"),
            )
            .outerjoin(
                trace_context_subquery, trace_context_subquery.c.trace_id == OtelSpan.trace_id
            )
            .where(OtelSpan.total_cost.is_not(None))
            .where(response_cost_span_condition(OtelSpan))
            .where(conversation_id_expr.is_not(None))
        )
        if conversation_ids:
            stmt = stmt.where(conversation_id_expr.in_(conversation_ids))
        return stmt.group_by(conversation_id_expr).subquery()

    message_feedback_subquery = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.sum(case((MessageFeedback.rating == MessageRating.THUMBS_UP, 1), else_=0)).label(
                "message_feedback_up"
            ),
            func.sum(case((MessageFeedback.rating == MessageRating.THUMBS_DOWN, 1), else_=0)).label(
                "message_feedback_down"
            ),
        )
        .join(MessageFeedback, MessageFeedback.message_id == Message.id)
        .group_by(Message.conversation_id)
        .subquery()
    )

    conversation_feedback_subquery = (
        select(
            ConversationFeedback.conversation_id.label("conversation_id"),
            func.sum(
                case((ConversationFeedback.rating == MessageRating.THUMBS_UP, 1), else_=0)
            ).label("conversation_feedback_up"),
            func.sum(
                case((ConversationFeedback.rating == MessageRating.THUMBS_DOWN, 1), else_=0)
            ).label("conversation_feedback_down"),
        )
        .group_by(ConversationFeedback.conversation_id)
        .subquery()
    )

    message_count = func.coalesce(message_count_subquery.c.message_count, 0).label("message_count")
    feedback_up = (
        func.coalesce(message_feedback_subquery.c.message_feedback_up, 0)
        + func.coalesce(conversation_feedback_subquery.c.conversation_feedback_up, 0)
    ).label("feedback_up")
    feedback_down = (
        func.coalesce(message_feedback_subquery.c.message_feedback_down, 0)
        + func.coalesce(conversation_feedback_subquery.c.conversation_feedback_down, 0)
    ).label("feedback_down")
    effective_updated_at = func.coalesce(
        latest_message_time_subquery.c.latest_message_time, Conversation.created_at
    ).label("effective_updated_at")

    public_name_expr = func.nullif(
        func.trim(func.concat(PublicChatContact.first_name, " ", PublicChatContact.last_name)), ""
    )
    user_name_expr = case(
        (Conversation.is_public.is_(True), public_name_expr), else_=User.name
    ).label("user_name")
    user_email_expr = case(
        (Conversation.is_public.is_(True), PublicChatContact.email), else_=User.email
    ).label("user_email")

    include_cost_in_query = page_params.sort_by == "total_cost"

    base_stmt = (
        select(
            Conversation,
            message_count,
            last_message_subquery.c.role.label("last_message_role"),
            last_message_subquery.c.content.label("last_message_content"),
            last_message_subquery.c.guardrails_blocked.label("last_message_guardrails_blocked"),
            last_message_subquery.c.guardrails_blocked_message.label(
                "last_message_guardrails_blocked_message"
            ),
            effective_updated_at,
            feedback_up,
            feedback_down,
            user_name_expr,
            user_email_expr,
        )
        .outerjoin(User, Conversation.user_id == User.id)
        .outerjoin(RbacGroup, User.group_id == RbacGroup.id)
        .outerjoin(PublicChatContact, Conversation.id == PublicChatContact.conversation_id)
        .outerjoin(
            message_count_subquery, Conversation.id == message_count_subquery.c.conversation_id
        )
        .outerjoin(
            last_message_subquery,
            (Conversation.id == last_message_subquery.c.conversation_id)
            & (last_message_subquery.c.rn == 1),
        )
        .outerjoin(
            latest_message_time_subquery,
            Conversation.id == latest_message_time_subquery.c.conversation_id,
        )
        .outerjoin(
            message_feedback_subquery,
            Conversation.id == message_feedback_subquery.c.conversation_id,
        )
        .outerjoin(
            conversation_feedback_subquery,
            Conversation.id == conversation_feedback_subquery.c.conversation_id,
        )
    )

    total_cost: Any = type_cast(Any, cast(literal(None), Float).label("total_cost"))
    cost_subquery: Any | None = None
    if include_cost_in_query:
        cost_subquery_local = _build_cost_subquery()
        cost_subquery = cost_subquery_local
        total_cost = type_cast(
            Any, cast(cost_subquery_local.c.total_cost, Float).label("total_cost")
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
    base_stmt = base_stmt.where(Conversation.kind == kind)

    if start is not None:
        base_stmt = base_stmt.where(effective_updated_at >= start)
    if end is not None:
        base_stmt = base_stmt.where(effective_updated_at <= end)

    if search is not None and search.strip() != "":
        search_text = search.strip()
        contact_search_conditions = _build_public_contact_search_conditions(
            search_text, phrase_search=phrase_search
        )
        base_stmt = base_stmt.where(
            or_(
                *_build_conversation_search_conditions(search_text, phrase_search=phrase_search),
                *contact_search_conditions,
            )
        )

    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)

    if user_email is not None and user_email.strip() != "":
        normalized_email = user_email.strip()
        user_conditions: list[Any] = []
        if include_internal:
            user_conditions.append(User.email == normalized_email)
        if include_public:
            user_conditions.append(PublicChatContact.email == normalized_email)
        base_stmt = base_stmt.where(or_(*user_conditions) if user_conditions else false())

    base_stmt = build_owner_group_filter(
        base_stmt,
        owner_group=user_group,
        include_internal=include_internal,
        permission_map=permission_map,
    )

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt: Any = base_stmt.add_columns(total_cost)
    if include_cost_in_query and cost_subquery is not None:
        stmt = stmt.outerjoin(
            cost_subquery, Conversation.id == cast(cost_subquery.c.conversation_id, PGUUID)
        )

    sort_map: dict[str, Any] = {
        "updated_at": effective_updated_at,
        "created_at": Conversation.created_at,
        "message_count": message_count,
        "feedback_up": feedback_up,
        "feedback_down": feedback_down,
        "title": Conversation.title,
        "total_cost": total_cost,
    }
    sort_column: Any = sort_map.get(page_params.sort_by, effective_updated_at)

    stmt = (
        stmt.order_by(sort_column.desc() if page_params.descending else sort_column.asc())
        .offset(page_params.offset)
        .limit(page_params.limit)
    )

    rows = (await session.execute(stmt)).all()

    cost_map: dict[UUID, float | None] = {}
    if not include_cost_in_query and rows:
        conversation_ids = [conversation.id for (conversation, *_) in rows]
        cost_subquery_local = _build_cost_subquery(conversation_ids)
        cost_total: Any = type_cast(
            Any, cast(cost_subquery_local.c.total_cost, Float).label("total_cost")
        )
        conversation_id_label: Any = type_cast(
            Any, cast(cost_subquery_local.c.conversation_id, PGUUID).label("conversation_id")
        )
        cost_stmt: Any = select(conversation_id_label, cost_total)
        cost_rows = (await session.execute(cost_stmt)).mappings().all()
        cost_map = {row["conversation_id"]: row["total_cost"] for row in cost_rows}

    items = [
        ConversationListItem(
            id=conversation.id,
            title=conversation.title,
            summary=conversation.summary,
            last_message_preview=(
                _format_message_preview(preview_content) if preview_content else None
            ),
            message_count=message_count_value,
            created_at=conversation.created_at,
            updated_at=updated_at,
            is_public=conversation.is_public,
            user_name=user_name_value,
            user_email=user_email_value,
            total_cost=total_cost_value if include_cost_in_query else cost_map.get(conversation.id),
            feedback_up=feedback_up_value,
            feedback_down=feedback_down_value,
        )
        for (
            conversation,
            message_count_value,
            last_role,
            last_content,
            last_guardrails_blocked,
            last_guardrails_blocked_message,
            updated_at,
            feedback_up_value,
            feedback_down_value,
            user_name_value,
            user_email_value,
            total_cost_value,
        ) in rows
        for preview_content in [
            _message_preview_content(
                role=last_role,
                content=last_content,
                guardrails_blocked=last_guardrails_blocked,
                guardrails_blocked_message=last_guardrails_blocked_message,
            )
        ]
    ]

    return ConversationListPage(items=items, total=total)


@router.get(
    "/{conversation_id}", response_model=ConversationDetail, response_model_exclude_none=True
)
async def get_internal_conversation(
    conversation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
    source: Annotated[
        Literal["chat", "chats", "messages", "investigate", "investigations"], Query()
    ] = "chat",
    target_message_id: Annotated[UUID | None, Query()] = None,
) -> Any:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await _ensure_conversation_access_for_source(session, conversation, current_user, source)
    permission_map = await get_effective_permission_map(session, current_user)
    can_view_response_cost = permission_map.get(PermissionKey.CHAT_VIEW_RESPONSE_COST, False)
    can_view_guardrails_failures = permission_map.get(
        PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES, False
    )
    can_view_sources = permission_map.get(PermissionKey.CHAT_VIEW_SOURCES, False)
    can_view_tools = permission_map.get(PermissionKey.CHAT_VIEW_TOOLS, False)
    owner = (
        await session.get(User, conversation.user_id) if conversation.user_id is not None else None
    )
    public_contact = None
    if conversation.is_public:
        public_contact = await session.scalar(
            select(PublicChatContact).where(PublicChatContact.conversation_id == conversation.id)
        )

    if target_message_id is not None:
        target_message = await _get_message_or_404(session, target_message_id)
        if target_message.conversation_id != conversation_id:
            raise HTTPException(
                status_code=400, detail="Target message is not in this conversation"
            )
        path_ids = await _get_conversation_path_through_message(session, target_message_id)
    else:
        path_ids = await get_current_branch_path(session, conversation_id)
    messages: list[Message] = []
    feedback_by_message_id: dict[UUID, list[MessageFeedback]] = {}

    if path_ids:
        stmt = (
            select(Message)
            .options(
                joinedload(Message.feedback).joinedload(MessageFeedback.user),
                joinedload(Message.assistant_message_metadata),
            )
            .where(Message.id.in_(path_ids))
        )
        result = await session.execute(stmt)
        messages_by_id = {message.id: message for message in result.scalars().unique().all()}
        messages = [
            messages_by_id[message_id] for message_id in path_ids if message_id in messages_by_id
        ]
        for message in messages:
            feedback_by_message_id[message.id] = list(message.feedback)

    updated_at = max((message.created_at for message in messages), default=conversation.created_at)
    response_cost_by_message_id: dict[UUID, float] = {}
    response_usage_by_message_id: dict[UUID, ConversationMessageResponseUsage] = {}
    response_cost_breakdown_by_message_id: dict[UUID, ConversationMessageResponseCostBreakdown] = {}
    guardrails_failures_by_message_id: dict[UUID, list[GuardrailsFailureOut]] = {}
    tool_sources_used_by_message_id: dict[UUID, list[MessageSourceUsed]] = {}
    message_ids = (
        [message.id for message in messages if message.role == "assistant"] if messages else []
    )
    if message_ids and (can_view_sources or can_view_tools):
        tool_sources_used_by_message_id = await get_tool_sources_used_by_message_ids(
            session, message_ids
        )
    generation_timing_by_message_id = await _get_generation_timing_by_message_id(
        session, message_ids
    )
    if message_ids and (can_view_response_cost or can_view_guardrails_failures):
        latest_trace_ranked = (
            select(
                OtelSpan.message_id.label("message_id"),
                OtelSpan.trace_id.label("trace_id"),
                func.row_number()
                .over(
                    partition_by=OtelSpan.message_id,
                    order_by=(OtelSpan.start_time.desc().nullslast(), OtelSpan.created_at.desc()),
                )
                .label("rank"),
            )
            .where(OtelSpan.message_id.in_(message_ids))
            .subquery()
        )
        latest_trace_rows = (
            await session.execute(
                select(latest_trace_ranked.c.message_id, latest_trace_ranked.c.trace_id).where(
                    latest_trace_ranked.c.rank == 1
                )
            )
        ).all()
        trace_to_message_id = {trace_id: message_id for message_id, trace_id in latest_trace_rows}
        if trace_to_message_id:
            trace_ids = list(trace_to_message_id.keys())
            if can_view_guardrails_failures:
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
                        .where(OtelSpan.trace_id.in_(trace_ids))
                        .where(_guardrails_trace_span_condition())
                    )
                ).all()
                spans_by_trace_id: dict[str, list[GuardrailsTraceSpan]] = {}
                for row in guardrails_span_rows:
                    span = GuardrailsTraceSpan(*row)
                    spans_by_trace_id.setdefault(span.trace_id, []).append(span)

                for trace_id, spans in spans_by_trace_id.items():
                    message_id = trace_to_message_id.get(trace_id)
                    if message_id is None:
                        continue
                    failures = guardrails_failures_from_spans(spans)
                    if failures is not None:
                        guardrails_failures_by_message_id[message_id] = failures

            if can_view_response_cost:
                cost_span_rows = (
                    await session.execute(
                        select(
                            OtelSpan.trace_id,
                            OtelSpan.total_cost,
                            OtelSpan.input_tokens,
                            OtelSpan.output_tokens,
                            OtelSpan.attributes,
                            OtelSpan.created_at,
                        ).where(
                            OtelSpan.trace_id.in_(trace_ids),
                            OtelSpan.is_ai.is_(True),
                            OtelSpan.is_embedding.is_not(True),
                            response_cost_span_condition(OtelSpan),
                        )
                    )
                ).all()
                cost_spans_by_message_id: dict[UUID, list[ResponseCostSpan]] = {}
                for (
                    trace_id,
                    total_cost,
                    input_tokens,
                    output_tokens,
                    attributes,
                    span_created_at,
                ) in cost_span_rows:
                    message_id = trace_to_message_id.get(trace_id)
                    if message_id is None:
                        continue
                    cost_spans_by_message_id.setdefault(message_id, []).append(
                        ResponseCostSpan(
                            total_cost=total_cost,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            attributes=attributes,
                            created_at=span_created_at,
                        )
                    )

                for message_id, cost_spans in cost_spans_by_message_id.items():
                    cost_summary = summarize_response_costs(cost_spans)
                    if cost_summary.response_cost is not None:
                        response_cost_by_message_id[message_id] = cost_summary.response_cost
                    if cost_summary.cost_breakdown is not None:
                        response_cost_breakdown_by_message_id[message_id] = (
                            ConversationMessageResponseCostBreakdown(**cost_summary.cost_breakdown)
                        )
                    if (
                        usage := _usage_or_none(
                            input_tokens=cost_summary.input_tokens,
                            cache_read_input_tokens=cost_summary.cache_read_input_tokens,
                            output_tokens=cost_summary.output_tokens,
                        )
                    ) is not None:
                        response_usage_by_message_id[message_id] = usage

    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        summary=conversation.summary,
        is_public=conversation.is_public,
        user_name=(
            f"{public_contact.first_name} {public_contact.last_name}".strip()
            if public_contact is not None
            else owner.name
            if owner is not None
            else None
        ),
        user_email=(
            public_contact.email
            if public_contact is not None
            else owner.email
            if owner is not None
            else None
        ),
        investigation_source_conversation_id=conversation.investigation_source_conversation_id,
        investigation_source_message_id=conversation.investigation_source_message_id,
        investigation_source_feedback_id=conversation.investigation_source_feedback_id,
        messages=[
            ConversationMessageWithFeedback(
                id=message.id,
                role=message.role,
                content=message.content,
                parent_id=message.parent_id,
                created_at=message.created_at,
                guardrails_blocked=message.guardrails_blocked,
                guardrails_blocked_message=_blocked_display_message(
                    blocked=message.guardrails_blocked,
                    blocked_message=message.guardrails_blocked_message,
                ),
                assistant_tool_calls=(
                    message.assistant_message_metadata.tool_calls
                    if message.assistant_message_metadata is not None
                    else None
                ),
                tool_sources_used=(
                    tool_sources_used_by_message_id.get(message.id, []) if can_view_tools else []
                ),
                grounding_sources_used=(
                    filter_sources_by_keys(
                        with_canned_response_source_candidate(
                            tool_sources_used_by_message_id.get(message.id, [])
                        ),
                        message.assistant_message_metadata.grounding_source_keys
                        if message.assistant_message_metadata is not None
                        else None,
                    )
                    if can_view_sources
                    else []
                ),
                grounding_source_status=(
                    message.assistant_message_metadata.grounding_source_status
                    if can_view_sources and message.assistant_message_metadata is not None
                    else None
                ),
                generation_time_ms=(
                    round(message.assistant_message_metadata.total_time * 1000)
                    if message.assistant_message_metadata is not None
                    and message.assistant_message_metadata.total_time is not None
                    else None
                ),
                generation_timing=_build_generation_timing(
                    message.assistant_message_metadata,
                    generation_timing_by_message_id.get(message.id),
                ),
                response_cost=response_cost_by_message_id.get(message.id),
                response_usage=response_usage_by_message_id.get(message.id),
                response_cost_breakdown=response_cost_breakdown_by_message_id.get(message.id),
                guardrails_failures=guardrails_failures_by_message_id.get(message.id),
                feedback=[
                    ConversationMessageFeedback(
                        id=feedback.id,
                        rating=feedback.rating,
                        text=feedback.text,
                        user_id=feedback.user_id,
                        user_name=feedback.user.name,
                        is_current_user=feedback.user_id == current_user.id,
                        created_at=feedback.created_at,
                        updated_at=feedback.updated_at,
                    )
                    for feedback in feedback_by_message_id.get(message.id, [])
                ],
            )
            for message in messages
        ],
        created_at=conversation.created_at,
        updated_at=updated_at,
    )


@router.put("/{conversation_id}/title", response_model=ConversationTitleOut)
async def update_internal_conversation_title(
    conversation_id: UUID,
    request: ConversationTitleUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await _ensure_internal_conversation_access(session, conversation, current_user)

    if conversation.is_public:
        raise HTTPException(status_code=400, detail="Cannot rename public conversation")

    title = request.title.strip()
    if title == "":
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    conversation.title = title
    await session.commit()
    await session.refresh(conversation)
    return ConversationTitleOut(title=title)


@router.post("/{conversation_id}/title/regenerate", response_model=ConversationTitleOut)
async def regenerate_internal_conversation_title(
    conversation_id: UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await _ensure_internal_conversation_access(session, conversation, current_user)

    if conversation.is_public:
        raise HTTPException(
            status_code=400, detail="Cannot regenerate title for public conversation"
        )

    path_ids = await get_current_branch_path(session, conversation_id)
    if not path_ids:
        return ConversationTitleOut(title=conversation.title or "")

    result = await session.execute(select(Message).where(Message.id.in_(path_ids)))
    messages_by_id = {message.id: message for message in result.scalars().all()}
    ordered_messages = [
        messages_by_id[message_id] for message_id in path_ids if message_id in messages_by_id
    ]

    if not ordered_messages:
        return ConversationTitleOut(title=conversation.title or "")

    transcript = _build_transcript(ordered_messages, is_internal=True)
    fallback = conversation.title or build_fallback_title(ordered_messages[0].content)
    title = await generate_conversation_title_from_transcript(
        transcript, conversation_id=conversation_id, is_internal=True, fallback=fallback
    )

    conversation.title = title
    await session.commit()
    await session.refresh(conversation)

    return ConversationTitleOut(title=title)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_internal_conversation(
    conversation_id: UUID, session: SessionDep, current_user: CurrentUser
) -> None:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await _ensure_internal_conversation_access(session, conversation, current_user)

    if conversation.is_public and not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    await session.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.active_child_id.is_not(None))
        .values(active_child_id=None)
    )
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await session.delete(conversation)
    await session.commit()


@router.get("/{conversation_id}/tree", response_model=ConversationDetailTreeOut)
async def get_conversation_tree(
    conversation_id: UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await _ensure_internal_conversation_access(session, conversation, current_user)

    stmt = (
        select(Message)
        .options(joinedload(Message.feedback).joinedload(MessageFeedback.user))
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = list((await session.execute(stmt)).scalars().unique().all())
    current_branch_path = await get_current_branch_path(session, conversation_id)

    nodes_by_id: dict[UUID, MessageTreeNodeOut] = {}
    children_by_parent: dict[UUID, list[UUID]] = {}

    for message in messages:
        feedback = [
            Feedback(
                id=item.id,
                rating=item.rating,
                text=item.text,
                user_id=item.user_id,
                user_name=item.user.name,
                is_current_user=item.user_id == current_user.id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in message.feedback
        ]
        nodes_by_id[message.id] = MessageTreeNodeOut(
            message=MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                parent_id=message.parent_id,
                feedback=feedback,
                guardrails_blocked=message.guardrails_blocked,
                guardrails_blocked_message=_blocked_display_message(
                    blocked=message.guardrails_blocked,
                    blocked_message=message.guardrails_blocked_message,
                ),
            ),
            message_tree_nodes=[],
        )
        children_by_parent[message.id] = []

    root_nodes: dict[UUID, MessageTreeNodeOut] = {}
    for message in messages:
        if message.parent_id is None:
            root_nodes[message.id] = nodes_by_id[message.id]
        else:
            children_by_parent.setdefault(message.parent_id, []).append(message.id)

    def attach_children(message_id: UUID) -> MessageTreeNodeOut:
        node = nodes_by_id[message_id]
        child_ids = sorted(
            children_by_parent.get(message_id, []),
            key=lambda child_id: nodes_by_id[child_id].message.created_at,
        )
        node.message_tree_nodes = [attach_children(child_id) for child_id in child_ids]
        return node

    tree_nodes = {message_id: attach_children(message_id) for message_id in root_nodes}

    return ConversationDetailTreeOut(
        id=conversation.id,
        title=conversation.title,
        user=conversation.user,
        conversation_tree=ConversationTreeOut(
            message_tree_nodes=tree_nodes,
            current_branch_path=current_branch_path,
            subtree_active_paths={},
        ),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def create_message_feedback(
    message_id: UUID,
    feedback_request: FeedbackIn,
    session: SessionDep,
    current_user: CurrentUser,
    source: Annotated[Literal["chat", "chats"], Query()] = "chat",
) -> Any:
    message = await _get_message_or_404(session, message_id)
    conversation = await _get_conversation_or_404(session, message.conversation_id)
    await _ensure_conversation_access_for_source(session, conversation, current_user, source)

    existing = await session.scalar(
        select(MessageFeedback)
        .options(joinedload(MessageFeedback.user))
        .where(MessageFeedback.message_id == message_id, MessageFeedback.user_id == current_user.id)
    )

    if existing is not None:
        existing.rating = feedback_request.rating
        existing.text = feedback_request.text
        await session.commit()
        await session.refresh(existing)
        existing = await _get_message_feedback_or_404(session, existing.id)
        return await _build_feedback_out(existing, current_user)

    feedback = MessageFeedback(
        message_id=message_id,
        user_id=current_user.id,
        rating=feedback_request.rating,
        text=feedback_request.text,
    )
    session.add(feedback)
    await session.commit()
    feedback = await _get_message_feedback_or_404(session, feedback.id)
    return await _build_feedback_out(feedback, current_user)


@router.get("/messages/{message_id}/feedback", response_model=list[FeedbackOut])
async def get_message_feedback(
    message_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
    source: Annotated[Literal["chat", "chats"], Query()] = "chat",
) -> Any:
    message = await _get_message_or_404(session, message_id)
    conversation = await _get_conversation_or_404(session, message.conversation_id)
    await _ensure_conversation_access_for_source(session, conversation, current_user, source)

    stmt = (
        select(MessageFeedback)
        .options(joinedload(MessageFeedback.user))
        .where(MessageFeedback.message_id == message_id)
        .order_by(MessageFeedback.created_at)
    )
    feedback_items = list((await session.execute(stmt)).scalars().all())
    return [await _build_feedback_out(feedback, current_user) for feedback in feedback_items]


@router.delete("/messages/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_feedback(
    feedback_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
    source: Annotated[Literal["chat", "chats"], Query()] = "chat",
) -> None:
    feedback = await _get_message_feedback_or_404(session, feedback_id)
    message = await _get_message_or_404(session, feedback.message_id)
    conversation = await _get_conversation_or_404(session, message.conversation_id)
    await _ensure_conversation_access_for_source(session, conversation, current_user, source)

    if feedback.user_id != current_user.id and not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    await session.delete(feedback)
    await session.commit()


@router.put("/messages/{message_id}/active-child")
async def update_message_active_child(
    message_id: UUID, request: UpdateActiveChildIn, session: SessionDep, current_user: CurrentUser
) -> None:
    message = await _get_message_or_404(session, message_id)
    conversation = await _get_conversation_or_404(session, message.conversation_id)
    await _ensure_internal_conversation_access(session, conversation, current_user)

    active_child_id = UUID(request.active_child_id) if request.active_child_id else None
    if active_child_id is not None:
        active_child = await _get_message_or_404(session, active_child_id)
        if active_child.parent_id != message_id:
            raise HTTPException(
                status_code=400, detail="Active child must be a direct child of this message"
            )

    await update_active_child_for_branch_switch(session, message_id, active_child_id)
