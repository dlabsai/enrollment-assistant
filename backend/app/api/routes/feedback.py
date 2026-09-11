from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import CurrentUser, SessionDep
from app.api.excel_export import (
    XLSX_MEDIA_TYPE,
    ExcelExportCell,
    ExcelExportWorkbook,
    ExportDateTimeFormatter,
    excel_safe_text,
)
from app.api.routes.owner_group_filter import (
    OwnerGroup,
    build_owner_group_filter,
    validate_exclusive_user_filters,
)
from app.api.routes.time_filters import AwareTimestamp, validate_time_range
from app.core.rbac import (
    PermissionKey,
    get_allowed_chat_owner_group_slugs,
    get_effective_permission_map,
)
from app.models import Conversation, Message, MessageFeedback, RbacGroup, User
from app.models import Rating as MessageRating

router = APIRouter(prefix="/feedback", tags=["feedback"])


_EXPORT_HEADERS = (
    "Thumbs",
    "Feedback text",
    "User message",
    "Assistant message",
    "Transcript URL",
    "Chat",
    "Chat user name",
    "Chat user email",
    "Feedback by name",
    "Feedback by email",
    "Created",
)
_EXPORT_COLUMN_WIDTHS = (14, 36, 54, 54, 64, 32, 24, 32, 24, 32, 22)

_PREVIEW_MAX_LENGTH = 160


class FeedbackListItem(BaseModel):
    id: UUID
    message_id: UUID
    conversation_id: UUID
    rating: MessageRating
    text: str | None = None
    message_role: str
    message_preview: str
    conversation_title: str | None = None
    conversation_summary: str | None = None
    is_public: bool
    conversation_user_name: str | None = None
    conversation_user_email: str | None = None
    feedback_user_name: str
    feedback_user_email: str
    created_at: datetime
    updated_at: datetime


class FeedbackListPage(BaseModel):
    items: list[FeedbackListItem]
    total: int


@dataclass(frozen=True)
class FeedbackQueryItem:
    id: UUID
    message_id: UUID
    conversation_id: UUID
    rating: MessageRating
    text: str | None
    message_role: str
    message_content: str
    user_message_content: str | None
    conversation_title: str | None
    conversation_summary: str | None
    is_public: bool
    conversation_user_name: str | None
    conversation_user_email: str | None
    feedback_user_name: str
    feedback_user_email: str
    created_at: datetime
    updated_at: datetime


def _is_admin_user(current_user: CurrentUser) -> bool:
    return current_user.group.slug in {"admin", "dev"}


def _format_preview(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) > _PREVIEW_MAX_LENGTH:
        return normalized[:_PREVIEW_MAX_LENGTH] + "..."
    return normalized


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


async def _get_feedback_permission_map(
    session: SessionDep, current_user: CurrentUser
) -> dict[PermissionKey, bool]:
    permission_map = await get_effective_permission_map(session, current_user)
    if not permission_map.get(PermissionKey.ACCESS_CHATS, False):
        raise HTTPException(status_code=403, detail="Access denied")
    return permission_map


def _build_feedback_base_stmt(
    current_user: CurrentUser,
    *,
    permission_map: dict[PermissionKey, bool],
    platform: Literal["internal", "public"] | None,
    rating: MessageRating | None,
    search: str | None,
    exclude_draft: bool,
    user_email: str | None,
    user_group: OwnerGroup | None,
    start: datetime | None,
    end: datetime | None,
    end_before: datetime | None,
) -> Any:
    validate_time_range(start, end, end_before)
    include_internal, include_public = _get_platform_scope(current_user, platform)
    internal_visibility_condition = _internal_visibility_condition(
        current_user, permission_map=permission_map
    )

    # SQLAlchemy aliases are needed because feedback author and conversation owner are both users.
    feedback_user_alias = aliased(User)
    owner_user_alias = aliased(User)
    user_message_alias = aliased(Message)

    conversation_user_name = owner_user_alias.name.label("conversation_user_name")
    conversation_user_email = owner_user_alias.email.label("conversation_user_email")

    base_stmt = (
        select(
            MessageFeedback,
            Message,
            Conversation,
            feedback_user_alias.name.label("feedback_user_name"),
            feedback_user_alias.email.label("feedback_user_email"),
            conversation_user_name,
            conversation_user_email,
            user_message_alias.content.label("user_message_content"),
        )
        .join(Message, MessageFeedback.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(feedback_user_alias, MessageFeedback.user_id == feedback_user_alias.id)
        .outerjoin(
            user_message_alias,
            (Message.parent_id == user_message_alias.id) & (user_message_alias.role == "user"),
        )
        .outerjoin(owner_user_alias, Conversation.user_id == owner_user_alias.id)
        .outerjoin(RbacGroup, owner_user_alias.group_id == RbacGroup.id)
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
    base_stmt = base_stmt.where(Conversation.kind == "chat", Message.role == "assistant")
    if exclude_draft:
        base_stmt = base_stmt.where(
            or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft")
        )

    if rating is not None:
        base_stmt = base_stmt.where(MessageFeedback.rating == rating)
    if start is not None:
        base_stmt = base_stmt.where(MessageFeedback.created_at >= start)
    if end is not None:
        base_stmt = base_stmt.where(MessageFeedback.created_at <= end)
    if end_before is not None:
        base_stmt = base_stmt.where(MessageFeedback.created_at < end_before)
    if search is not None and search.strip() != "":
        pattern = f"%{search.strip()}%"
        base_stmt = base_stmt.where(
            or_(
                MessageFeedback.text.ilike(pattern),
                Message.content.ilike(pattern),
                Conversation.title.ilike(pattern),
                Conversation.summary.ilike(pattern),
                feedback_user_alias.name.ilike(pattern),
                feedback_user_alias.email.ilike(pattern),
                owner_user_alias.name.ilike(pattern),
                owner_user_alias.email.ilike(pattern),
                user_message_alias.content.ilike(pattern),
            )
        )
    validate_exclusive_user_filters(user_email=user_email, user_group=user_group)

    if user_email is not None and user_email.strip() != "":
        normalized_email = user_email.strip()
        user_conditions: list[Any] = []
        if include_internal:
            user_conditions.append(owner_user_alias.email == normalized_email)
        base_stmt = base_stmt.where(or_(*user_conditions) if user_conditions else false())

    return build_owner_group_filter(
        base_stmt,
        owner_group=user_group,
        include_internal=include_internal,
        permission_map=permission_map,
    )


def _sort_feedback_stmt(stmt: Any, *, sort_by: str, descending: bool) -> Any:
    sort_map: dict[str, Any] = {
        "created_at": MessageFeedback.created_at,
        "updated_at": MessageFeedback.updated_at,
        "rating": MessageFeedback.rating,
        "conversation_title": Conversation.title,
    }
    sort_column = sort_map.get(sort_by, MessageFeedback.created_at)
    return stmt.order_by(sort_column.desc() if descending else sort_column.asc())


def _row_to_feedback_query_item(row: Any) -> FeedbackQueryItem:
    (
        feedback,
        message,
        conversation,
        feedback_user_name,
        feedback_user_email,
        conversation_user_name_value,
        conversation_user_email_value,
        user_message_content,
    ) = row

    return FeedbackQueryItem(
        id=feedback.id,
        message_id=message.id,
        conversation_id=conversation.id,
        rating=feedback.rating,
        text=feedback.text,
        message_role=message.role,
        user_message_content=user_message_content,
        message_content=message.content,
        conversation_title=conversation.title,
        conversation_summary=conversation.summary,
        is_public=conversation.is_public,
        conversation_user_name=conversation_user_name_value,
        conversation_user_email=conversation_user_email_value,
        feedback_user_name=feedback_user_name,
        feedback_user_email=feedback_user_email,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def _query_item_to_feedback_list_item(item: FeedbackQueryItem) -> FeedbackListItem:
    return FeedbackListItem(
        id=item.id,
        message_id=item.message_id,
        conversation_id=item.conversation_id,
        rating=item.rating,
        text=item.text,
        message_role=item.message_role,
        message_preview=_format_preview(item.message_content),
        conversation_title=item.conversation_title,
        conversation_summary=item.conversation_summary,
        is_public=item.is_public,
        conversation_user_name=item.conversation_user_name,
        conversation_user_email=item.conversation_user_email,
        feedback_user_name=item.feedback_user_name,
        feedback_user_email=item.feedback_user_email,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _feedback_rating_label(rating: MessageRating) -> str:
    return "Down" if rating == MessageRating.THUMBS_DOWN else "Up"


def _build_message_url(message_url_base: str, conversation_id: UUID, message_id: UUID) -> str:
    base = message_url_base.split("#", maxsplit=1)[0]
    conversation_path = quote(str(conversation_id), safe="")
    message_query = quote(str(message_id), safe="")
    return f"{base}#/chats/{conversation_path}?message={message_query}"


def _build_feedback_workbook(
    items: list[FeedbackQueryItem],
    *,
    message_url_base: str,
    timestamp_formatter: ExportDateTimeFormatter,
) -> bytes:
    workbook = ExcelExportWorkbook(
        sheet_title="Feedback", headers=_EXPORT_HEADERS, column_widths=_EXPORT_COLUMN_WIDTHS
    )

    for item in items:
        message_url = _build_message_url(message_url_base, item.conversation_id, item.message_id)
        workbook.append(
            (
                _feedback_rating_label(item.rating),
                excel_safe_text(item.text),
                excel_safe_text(item.user_message_content),
                excel_safe_text(item.message_content),
                ExcelExportCell(excel_safe_text(message_url), hyperlink=message_url),
                excel_safe_text(item.conversation_title or "Untitled chat"),
                excel_safe_text(item.conversation_user_name),
                excel_safe_text(item.conversation_user_email),
                excel_safe_text(item.feedback_user_name),
                excel_safe_text(item.feedback_user_email),
                timestamp_formatter.format(item.created_at),
            )
        )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _feedback_export_filename(timestamp_formatter: ExportDateTimeFormatter) -> str:
    export_date = timestamp_formatter.format_date(datetime.now(UTC))
    return f"feedback-{export_date}.xlsx"


@router.get("/export")
async def export_feedback(
    session: SessionDep,
    current_user: CurrentUser,
    platform: Annotated[Literal["internal", "public"] | None, Query()] = None,
    rating: Annotated[MessageRating | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    exclude_draft: Annotated[bool, Query()] = False,
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
    start: Annotated[AwareTimestamp | None, Query()] = None,
    end: Annotated[AwareTimestamp | None, Query()] = None,
    end_before: Annotated[AwareTimestamp | None, Query()] = None,
    sort_by: Annotated[str, Query()] = "created_at",
    descending: Annotated[bool, Query()] = True,
    message_url_base: Annotated[str, Query()] = "",
    browser_time_zone: Annotated[str, Query()] = "UTC",
    browser_locale: Annotated[str, Query()] = "en-US",
) -> StreamingResponse:
    permission_map = await _get_feedback_permission_map(session, current_user)
    base_stmt = _build_feedback_base_stmt(
        current_user,
        permission_map=permission_map,
        platform=platform,
        rating=rating,
        search=search,
        exclude_draft=exclude_draft,
        user_email=user_email,
        user_group=user_group,
        start=start,
        end=end,
        end_before=end_before,
    )
    stmt = _sort_feedback_stmt(base_stmt, sort_by=sort_by, descending=descending)
    rows = (await session.execute(stmt)).all()
    items = [_row_to_feedback_query_item(row) for row in rows]
    timestamp_formatter = ExportDateTimeFormatter.resolve(
        time_zone=browser_time_zone, locale=browser_locale
    )
    workbook = _build_feedback_workbook(
        items, message_url_base=message_url_base, timestamp_formatter=timestamp_formatter
    )
    filename = _feedback_export_filename(timestamp_formatter)

    return StreamingResponse(
        BytesIO(workbook),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=FeedbackListPage)
async def list_feedback(
    session: SessionDep,
    current_user: CurrentUser,
    platform: Annotated[Literal["internal", "public"] | None, Query()] = None,
    rating: Annotated[MessageRating | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    exclude_draft: Annotated[bool, Query()] = False,
    user_email: Annotated[str | None, Query()] = None,
    user_group: Annotated[OwnerGroup | None, Query()] = None,
    start: Annotated[AwareTimestamp | None, Query()] = None,
    end: Annotated[AwareTimestamp | None, Query()] = None,
    end_before: Annotated[AwareTimestamp | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[str, Query()] = "created_at",
    descending: Annotated[bool, Query()] = True,
) -> FeedbackListPage:
    permission_map = await _get_feedback_permission_map(session, current_user)
    base_stmt = _build_feedback_base_stmt(
        current_user,
        permission_map=permission_map,
        platform=platform,
        rating=rating,
        search=search,
        exclude_draft=exclude_draft,
        user_email=user_email,
        user_group=user_group,
        start=start,
        end=end,
        end_before=end_before,
    )

    filtered_ids_stmt = base_stmt.with_only_columns(MessageFeedback.id, maintain_column_froms=True)
    page_rows = (
        await session.execute(
            _sort_feedback_stmt(
                filtered_ids_stmt.add_columns(func.count().over().label("page_total")),
                sort_by=sort_by,
                descending=descending,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if page_rows:
        total = int(page_rows[0].page_total)
        page_ids = [row[0] for row in page_rows]
        rows = (await session.execute(base_stmt.where(MessageFeedback.id.in_(page_ids)))).all()
        rows_by_id = {row[0].id: row for row in rows}
        items = [
            _row_to_feedback_query_item(rows_by_id[feedback_id])
            for feedback_id in page_ids
            if feedback_id in rows_by_id
        ]
    else:
        total_stmt = select(func.count()).select_from(filtered_ids_stmt.subquery())
        total = (await session.execute(total_stmt)).scalar() or 0
        items = []
    response = FeedbackListPage(
        total=total, items=[_query_item_to_feedback_list_item(item) for item in items]
    )
    # Release the reserved connection before FastAPI validates and serializes the response.
    await session.commit()
    return response
