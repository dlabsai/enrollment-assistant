from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.rbac import (
    ALL_PERMISSION_KEYS,
    PERMISSION_DEFINITIONS,
    PermissionKey,
    SystemGroupSlug,
    get_effective_permission_map,
    replace_group_permissions,
    replace_user_permission_overrides,
    user_has_permission,
)
from app.models import RbacGroup, RbacGroupPermission, RbacUserPermissionOverride, User

router = APIRouter(prefix="/rbac", tags=["rbac"])


class PermissionDefinitionOut(BaseModel):
    key: str
    label: str
    description: str
    category: str


class GroupPermissionOut(BaseModel):
    key: str
    enabled: bool


class RbacGroupOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[GroupPermissionOut]


class UserPermissionOverrideOut(BaseModel):
    key: str
    value: bool | None = None


class RbacUserOut(BaseModel):
    id: UUID
    email: str
    name: str
    group_id: UUID
    group_slug: str
    overrides: list[UserPermissionOverrideOut]
    effective_permissions: dict[str, bool]


class RbacBootstrapOut(BaseModel):
    permissions: list[PermissionDefinitionOut]
    groups: list[RbacGroupOut]
    users: list[RbacUserOut]


class UpdateGroupPermissionsIn(BaseModel):
    permission_keys: list[str]


class UpdateUserGroupIn(BaseModel):
    group_id: UUID


class UpdateUserOverridesIn(BaseModel):
    overrides: dict[str, bool | None]


async def _require_manage_rbac(session: SessionDep, current_user: CurrentUser) -> None:
    if not await user_has_permission(session, current_user, PermissionKey.ACCESS_RBAC):
        raise HTTPException(status_code=403, detail="Access denied")


async def _get_group_or_404(session: SessionDep, group_id: UUID) -> RbacGroup:
    group = await session.get(RbacGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="RBAC group not found")
    return group


async def _get_user_or_404(session: SessionDep, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _ensure_manage_rbac_retained(session: SessionDep) -> None:
    await session.flush()
    users = list((await session.execute(select(User))).scalars().all())
    for user in users:
        if await user_has_permission(session, user, PermissionKey.ACCESS_RBAC):
            return

    raise HTTPException(status_code=400, detail="At least one user must retain access_rbac access")


async def _build_group_out(session: SessionDep, group: RbacGroup) -> RbacGroupOut:
    rows = (
        (
            await session.execute(
                select(RbacGroupPermission.permission_key).where(
                    RbacGroupPermission.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    enabled = set(rows)
    return RbacGroupOut(
        id=group.id,
        slug=group.slug,
        name=group.name,
        description=group.description,
        is_system=group.is_system,
        permissions=[
            GroupPermissionOut(key=permission_key.value, enabled=permission_key.value in enabled)
            for permission_key in ALL_PERMISSION_KEYS
        ],
    )


async def _build_user_out(
    session: SessionDep, user: User, groups_by_id: dict[UUID, RbacGroup]
) -> RbacUserOut:
    group = groups_by_id.get(user.group_id)
    if group is None:
        raise HTTPException(status_code=500, detail="RBAC group missing")

    override_rows = (
        await session.execute(
            select(
                RbacUserPermissionOverride.permission_key, RbacUserPermissionOverride.is_allowed
            ).where(RbacUserPermissionOverride.user_id == user.id)
        )
    ).all()
    override_map = {row.permission_key: row.is_allowed for row in override_rows}
    effective = await get_effective_permission_map(session, user)

    return RbacUserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        group_id=group.id,
        group_slug=group.slug,
        overrides=[
            UserPermissionOverrideOut(
                key=permission_key.value, value=override_map.get(permission_key.value)
            )
            for permission_key in ALL_PERMISSION_KEYS
        ],
        effective_permissions={
            permission_key.value: is_allowed for permission_key, is_allowed in effective.items()
        },
    )


@router.get("/bootstrap", response_model=RbacBootstrapOut)
async def get_rbac_bootstrap(session: SessionDep, current_user: CurrentUser) -> RbacBootstrapOut:
    await _require_manage_rbac(session, current_user)

    groups = list(
        (await session.execute(select(RbacGroup).order_by(RbacGroup.slug.asc()))).scalars().all()
    )
    groups_by_id = {group.id: group for group in groups}
    users = list((await session.execute(select(User).order_by(User.email.asc()))).scalars().all())

    return RbacBootstrapOut(
        permissions=[
            PermissionDefinitionOut(
                key=definition.key.value,
                label=definition.label,
                description=definition.description,
                category=definition.category,
            )
            for definition in PERMISSION_DEFINITIONS
        ],
        groups=[await _build_group_out(session, group) for group in groups],
        users=[await _build_user_out(session, user, groups_by_id) for user in users],
    )


@router.put("/groups/{group_id}/permissions", response_model=RbacGroupOut)
async def update_group_permissions(
    group_id: UUID,
    payload: UpdateGroupPermissionsIn,
    session: SessionDep,
    current_user: CurrentUser,
) -> RbacGroupOut:
    await _require_manage_rbac(session, current_user)
    group = await _get_group_or_404(session, group_id)

    try:
        permission_keys = {
            PermissionKey(permission_key) for permission_key in payload.permission_keys
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid permission key") from exc

    await replace_group_permissions(session, group, permission_keys)
    await _ensure_manage_rbac_retained(session)
    await session.commit()
    return await _build_group_out(session, group)


@router.put("/users/{user_id}/group", response_model=RbacUserOut)
async def update_user_group(
    user_id: UUID, payload: UpdateUserGroupIn, session: SessionDep, current_user: CurrentUser
) -> RbacUserOut:
    await _require_manage_rbac(session, current_user)
    user = await _get_user_or_404(session, user_id)
    group = await _get_group_or_404(session, payload.group_id)

    if group.slug not in {slug.value for slug in SystemGroupSlug}:
        raise HTTPException(status_code=400, detail="Only system groups are supported")

    user.group_id = group.id
    await _ensure_manage_rbac_retained(session)
    await session.commit()
    groups_by_id = {group.id: group}
    return await _build_user_out(session, user, groups_by_id)


@router.put("/users/{user_id}/permission-overrides", response_model=RbacUserOut)
async def update_user_permission_overrides(
    user_id: UUID, payload: UpdateUserOverridesIn, session: SessionDep, current_user: CurrentUser
) -> RbacUserOut:
    await _require_manage_rbac(session, current_user)
    user = await _get_user_or_404(session, user_id)

    try:
        overrides = {
            PermissionKey(permission_key): is_allowed
            for permission_key, is_allowed in payload.overrides.items()
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid permission key") from exc

    await replace_user_permission_overrides(session, user, overrides)
    await _ensure_manage_rbac_retained(session)
    await session.commit()

    group = await session.get(RbacGroup, user.group_id)
    if group is None:
        raise HTTPException(status_code=500, detail="RBAC group missing")
    groups_by_id = {group.id: group}
    return await _build_user_out(session, user, groups_by_id)
