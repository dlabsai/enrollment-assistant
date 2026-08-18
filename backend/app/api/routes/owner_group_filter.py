from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select

from app.core.rbac import PermissionKey, get_allowed_chat_owner_group_slugs
from app.models import Conversation, PublicChatContact, RbacGroup, User

OwnerGroup = Literal["staff", "devs"]


def validate_exclusive_user_filters(user_email: str | None, user_group: OwnerGroup | None) -> None:
    if user_group is not None and user_email is not None and user_email.strip() != "":
        raise HTTPException(status_code=400, detail="Specify only one of user_email or user_group")


def apply_aggregate_owner_filter(
    base_stmt: Any,
    *,
    current_user: User,
    permission_map: dict[PermissionKey, bool],
    user_email: str | None,
    user_group: OwnerGroup | None,
    include_internal: bool,
) -> Any:
    normalized_email = user_email.strip() if user_email is not None else ""
    statement = base_stmt.outerjoin(User, Conversation.user_id == User.id).outerjoin(
        RbacGroup, User.group_id == RbacGroup.id
    )

    if normalized_email != "":
        internal_conditions: list[Any] = []
        if permission_map.get(PermissionKey.CHATS_VIEW_OWN, False):
            internal_conditions.append(Conversation.user_id == current_user.id)
        allowed_group_slugs = get_allowed_chat_owner_group_slugs(permission_map)
        if allowed_group_slugs:
            internal_conditions.append(RbacGroup.slug.in_(sorted(allowed_group_slugs)))
        internal_visibility = or_(*internal_conditions) if internal_conditions else false()
        public_user_match = (
            select(PublicChatContact.id)
            .where(
                PublicChatContact.conversation_id == Conversation.id,
                PublicChatContact.email == normalized_email,
            )
            .exists()
        )
        statement = statement.where(
            or_(
                and_(
                    Conversation.is_public.is_(False),
                    internal_visibility,
                    User.email == normalized_email,
                ),
                and_(Conversation.is_public.is_(True), public_user_match),
            )
        )

    return build_owner_group_filter(
        statement,
        owner_group=user_group,
        include_internal=include_internal,
        permission_map=permission_map,
    )


def build_owner_group_filter(
    base_stmt: Any,
    *,
    owner_group: OwnerGroup | None,
    include_internal: bool,
    permission_map: dict[PermissionKey, bool],
) -> Any:
    if owner_group is None:
        return base_stmt

    if not include_internal:
        return base_stmt.where(false())

    requested_slugs = {"user", "admin"} if owner_group == "staff" else {"dev"}

    allowed_group_slugs = get_allowed_chat_owner_group_slugs(permission_map)
    allowed_requested_slugs = sorted(requested_slugs & allowed_group_slugs)
    if not allowed_requested_slugs:
        return base_stmt.where(false())

    return base_stmt.where(RbacGroup.slug.in_(allowed_requested_slugs))
