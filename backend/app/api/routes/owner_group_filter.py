from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import false

from app.core.rbac import PermissionKey, get_allowed_chat_owner_group_slugs
from app.models import RbacGroup

OwnerGroup = Literal["staff", "devs"]


def validate_exclusive_user_filters(user_email: str | None, user_group: OwnerGroup | None) -> None:
    if user_group is not None and user_email is not None and user_email.strip() != "":
        raise HTTPException(status_code=400, detail="Specify only one of user_email or user_group")


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
