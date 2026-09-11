from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, false, literal, or_, select

from app.core.rbac import PermissionKey, get_allowed_chat_owner_group_slugs
from app.models import ComplianceItem, ComplianceScreening, Conversation, Message, RbacGroup, User

from .schemas import TranscriptMessage

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_CONTEXT_DEPTH = 512


def _owner_visibility(user: User, permissions: Mapping[PermissionKey, bool]) -> Any:
    return or_(
        and_(User.id == user.id, literal(permissions.get(PermissionKey.CHATS_VIEW_OWN, False))),
        RbacGroup.slug.in_(sorted(get_allowed_chat_owner_group_slugs(permissions))),
    )


class ScreeningUnavailableError(Exception):
    def __init__(self, code: str) -> None:
        # Only fixed error codes cross logging/API boundaries; never include source text.
        self.code = code
        super().__init__(code)


def source_selection(
    user: User, permissions: Mapping[PermissionKey, bool], start: datetime, end: datetime
) -> Select[tuple[UUID, UUID, UUID | None]]:
    return (
        select(Message.id, Message.conversation_id, Conversation.user_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .join(RbacGroup, RbacGroup.id == User.group_id)
        .where(
            Message.role == "assistant",
            Message.created_at >= start,
            Message.created_at <= end,
            Conversation.is_public.is_(False),
            Conversation.kind == "chat",
            or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
            RbacGroup.slug.in_(["user", "admin"]),
            _owner_visibility(user, permissions),
        )
    )


def visible_items(
    user: User, permissions: Mapping[PermissionKey, bool]
) -> Select[tuple[ComplianceItem]]:
    known_owner = and_(_owner_visibility(user, permissions), RbacGroup.slug.in_(["user", "admin"]))
    live_source = and_(
        ComplianceItem.message_id.is_not(None),
        Conversation.user_id == User.id,
        Conversation.is_public.is_(False),
        Conversation.kind == "chat",
        or_(Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"),
        known_owner,
    )
    tombstone = and_(
        ComplianceItem.message_id.is_(None),
        or_(known_owner, and_(User.id.is_(None), ComplianceScreening.created_by_id == user.id)),
    )
    return (
        select(ComplianceItem)
        .join(ComplianceScreening, ComplianceScreening.id == ComplianceItem.screening_id)
        .outerjoin(User, User.id == ComplianceItem.owner_id)
        .outerjoin(RbacGroup, RbacGroup.id == User.group_id)
        .outerjoin(Conversation, Conversation.id == ComplianceItem.conversation_id)
        .where(
            or_(live_source, tombstone)
            if permissions.get(PermissionKey.ACCESS_COMPLIANCE)
            else false()
        )
    )


def display_content(message: Message) -> str:
    if message.guardrails_blocked:
        if not message.guardrails_blocked_message:
            raise ScreeningUnavailableError("missing_display")
        return message.guardrails_blocked_message
    return message.content


async def load_transcript(
    session: AsyncSession, conversation_id: UUID, *, as_of: datetime, lock: bool = False
) -> list[TranscriptMessage]:
    statement = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.created_at <= as_of)
        .order_by(Message.created_at, Message.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(read=True)
    messages = list((await session.scalars(statement)).all())
    ids = {message.id for message in messages}
    children: dict[UUID | None, list[UUID]] = {}
    for message in messages:
        if message.role not in {"user", "assistant"} or (
            message.parent_id is not None and message.parent_id not in ids
        ):
            raise ScreeningUnavailableError("invalid_context")
        children.setdefault(message.parent_id, []).append(message.id)
    pending = [(id_, 0) for id_ in children.get(None, [])]
    visited: set[UUID] = set()
    while pending:
        id_, depth = pending.pop()
        if depth > MAX_CONTEXT_DEPTH:
            raise ScreeningUnavailableError("too_long")
        visited.add(id_)
        pending.extend((child, depth + 1) for child in children.get(id_, []))
    if not messages or visited != ids:
        raise ScreeningUnavailableError("invalid_context")
    return [
        TranscriptMessage(
            id=message.id,
            parent_id=message.parent_id,
            role=message.role,
            content=display_content(message),
            created_at=message.created_at,
        )
        for message in messages
    ]


def transcript_hash(transcript: Sequence[TranscriptMessage]) -> str:
    payload = json.dumps(
        [message.model_dump(mode="json") for message in transcript],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
