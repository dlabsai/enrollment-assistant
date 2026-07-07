from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.models import RbacGroup, RbacGroupPermission, RbacUserPermissionOverride, User

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


class SystemGroupSlug(StrEnum):
    USER = "user"
    ADMIN = "admin"
    DEV = "dev"


class PermissionKey(StrEnum):
    ACCESS_CHATS = "access_chats"
    ACCESS_INVESTIGATIONS = "access_investigations"
    ACCESS_MESSAGES = "access_messages"
    ACCESS_INSTRUCTIONS = "access_instructions"
    ACCESS_TRACES = "access_traces"
    ACCESS_RAG = "access_rag"
    ACCESS_RBAC = "access_rbac"
    ACCESS_USAGE = "access_usage"
    ACCESS_ANALYTICS = "access_analytics"
    ACCESS_PUBLIC_ANALYTICS = "access_public_analytics"
    ACCESS_EVALS = "access_evals"
    ACCESS_SETTINGS = "access_settings"
    ACCESS_RAG_VIEWER = "access_rag_viewer"
    ACCESS_RAG_EXCLUSIONS = "access_rag_exclusions"
    CHAT_REGENERATE = "chat_regenerate"
    CHAT_VIEW_ACTIVITY = "chat_view_activity"
    CHAT_VIEW_TRACE = "chat_view_trace"
    CHAT_MODEL_SELECTION = "chat_model_selection"
    CHAT_DURATION_TOOLTIP = "chat_duration_tooltip"
    CHAT_VIEW_RESPONSE_COST = "chat_view_response_cost"
    CHAT_VIEW_GUARDRAILS_FAILURES = "chat_view_guardrails_failures"
    CHAT_VIEW_SOURCES = "chat_view_sources"
    CHAT_VIEW_TOOLS = "chat_view_tools"
    CHATS_VIEW_OWN = "chats_view_own"
    CHATS_VIEW_USERS = "chats_view_users"
    CHATS_VIEW_ADMINS = "chats_view_admins"
    CHATS_VIEW_DEVS = "chats_view_devs"
    CHATS_VIEW_TRACE = "chats_view_trace"
    CHATS_VIEW_COST_COLUMN = "chats_view_cost_column"


@dataclass(frozen=True)
class PermissionDefinition:
    key: PermissionKey
    label: str
    description: str
    category: str


PERMISSION_DEFINITIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(
        key=PermissionKey.ACCESS_CHATS,
        label="Chats page",
        description="Access the Chats page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_INVESTIGATIONS,
        label="Investigations pages",
        description="Create, run, and review developer investigation chats.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_MESSAGES,
        label="Messages page",
        description="Access the message-level diagnostics page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_INSTRUCTIONS,
        label="Instructions page",
        description="Access the Instructions page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_TRACES,
        label="Traces page",
        description="Access the Traces page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_RAG,
        label="KB Builder page",
        description="Access the KB Builder page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_RBAC,
        label="Access Controls page",
        description="Access the Access Controls page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_USAGE,
        label="Usage page",
        description="Access the Usage page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_ANALYTICS,
        label="Chat Analytics page",
        description="Access the Chat Analytics page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_PUBLIC_ANALYTICS,
        label="Public Analytics page",
        description="Access the Public Analytics page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_EVALS,
        label="Evals page",
        description="Access the Evals page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_SETTINGS,
        label="Settings page",
        description="Access the Settings page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_RAG_VIEWER,
        label="KB Viewer page",
        description="Access the KB Viewer page.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.ACCESS_RAG_EXCLUSIONS,
        label="KB Controls page",
        description="Access KB Controls and manage assistant content visibility.",
        category="pages",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_REGENERATE,
        label="Chat: regenerate",
        description="Regenerate assistant responses on the Chat page.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_ACTIVITY,
        label="Chat: activity",
        description="View assistant activity on the Chat page.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_TRACE,
        label="Chat: trace",
        description="Open trace details from the Chat page.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_MODEL_SELECTION,
        label="Chat: model selection",
        description="Use model selection on the Chat page.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_DURATION_TOOLTIP,
        label="Chat: duration tooltip",
        description="View the generation timing tooltip on the Chat page.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_RESPONSE_COST,
        label="Chat: response cost",
        description="View per-response cost diagnostics in message footers.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES,
        label="Chat: guardrails failures",
        description="View raw failed guardrails attempts in message footers.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_SOURCES,
        label="Chat: sources",
        description="View LLM-selected sources that ground assistant answers.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHAT_VIEW_TOOLS,
        label="Chat: tools",
        description="View the full source-producing tool activity for assistant generation.",
        category="chat",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_OWN,
        label="Chats: view own",
        description="View conversations owned by the current user on the Chats page.",
        category="chats",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_USERS,
        label="Chats: view users",
        description="View conversations owned by users in the 'user' group on the Chats page.",
        category="chats",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_ADMINS,
        label="Chats: view admins",
        description="View conversations owned by users in the 'admin' group on the Chats page.",
        category="chats",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_DEVS,
        label="Chats: view devs",
        description="View conversations owned by users in the 'dev' group on the Chats page.",
        category="chats",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_TRACE,
        label="Chats: trace",
        description="Open trace details from the Chats page.",
        category="chats",
    ),
    PermissionDefinition(
        key=PermissionKey.CHATS_VIEW_COST_COLUMN,
        label="Chats: cost column",
        description="View the cost column on the Chats page.",
        category="chats",
    ),
)


ALL_PERMISSION_KEYS: tuple[PermissionKey, ...] = tuple(
    definition.key for definition in PERMISSION_DEFINITIONS
)

SYSTEM_GROUP_SPECS: tuple[tuple[SystemGroupSlug, str], ...] = (
    (SystemGroupSlug.USER, "Standard staff access"),
    (SystemGroupSlug.ADMIN, "Administrative access"),
    (SystemGroupSlug.DEV, "Developer access"),
)

DEFAULT_GROUP_PERMISSIONS: dict[SystemGroupSlug, frozenset[PermissionKey]] = {
    SystemGroupSlug.USER: frozenset(
        {
            PermissionKey.CHAT_REGENERATE,
            PermissionKey.CHAT_VIEW_ACTIVITY,
            PermissionKey.CHAT_VIEW_TRACE,
            PermissionKey.CHAT_MODEL_SELECTION,
            PermissionKey.CHAT_DURATION_TOOLTIP,
            PermissionKey.CHAT_VIEW_SOURCES,
            PermissionKey.CHATS_VIEW_OWN,
        }
    ),
    SystemGroupSlug.ADMIN: frozenset(
        {
            PermissionKey.ACCESS_CHATS,
            PermissionKey.ACCESS_INSTRUCTIONS,
            PermissionKey.ACCESS_TRACES,
            PermissionKey.ACCESS_RAG,
            PermissionKey.ACCESS_USAGE,
            PermissionKey.ACCESS_ANALYTICS,
            PermissionKey.ACCESS_PUBLIC_ANALYTICS,
            PermissionKey.ACCESS_EVALS,
            PermissionKey.ACCESS_SETTINGS,
            PermissionKey.ACCESS_RAG_VIEWER,
            PermissionKey.ACCESS_RAG_EXCLUSIONS,
            PermissionKey.CHAT_REGENERATE,
            PermissionKey.CHAT_VIEW_ACTIVITY,
            PermissionKey.CHAT_VIEW_TRACE,
            PermissionKey.CHAT_MODEL_SELECTION,
            PermissionKey.CHAT_DURATION_TOOLTIP,
            PermissionKey.CHAT_VIEW_SOURCES,
            PermissionKey.CHATS_VIEW_OWN,
            PermissionKey.CHATS_VIEW_USERS,
            PermissionKey.CHATS_VIEW_ADMINS,
            PermissionKey.CHATS_VIEW_DEVS,
            PermissionKey.CHATS_VIEW_TRACE,
            PermissionKey.CHATS_VIEW_COST_COLUMN,
        }
    ),
    SystemGroupSlug.DEV: frozenset(
        {
            PermissionKey.ACCESS_CHATS,
            PermissionKey.ACCESS_INVESTIGATIONS,
            PermissionKey.ACCESS_MESSAGES,
            PermissionKey.ACCESS_INSTRUCTIONS,
            PermissionKey.ACCESS_TRACES,
            PermissionKey.ACCESS_RAG,
            PermissionKey.ACCESS_RBAC,
            PermissionKey.ACCESS_USAGE,
            PermissionKey.ACCESS_ANALYTICS,
            PermissionKey.ACCESS_PUBLIC_ANALYTICS,
            PermissionKey.ACCESS_EVALS,
            PermissionKey.ACCESS_SETTINGS,
            PermissionKey.ACCESS_RAG_VIEWER,
            PermissionKey.ACCESS_RAG_EXCLUSIONS,
            PermissionKey.CHAT_REGENERATE,
            PermissionKey.CHAT_VIEW_ACTIVITY,
            PermissionKey.CHAT_VIEW_TRACE,
            PermissionKey.CHAT_MODEL_SELECTION,
            PermissionKey.CHAT_DURATION_TOOLTIP,
            PermissionKey.CHAT_VIEW_RESPONSE_COST,
            PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES,
            PermissionKey.CHAT_VIEW_SOURCES,
            PermissionKey.CHAT_VIEW_TOOLS,
            PermissionKey.CHATS_VIEW_OWN,
            PermissionKey.CHATS_VIEW_USERS,
            PermissionKey.CHATS_VIEW_ADMINS,
            PermissionKey.CHATS_VIEW_DEVS,
            PermissionKey.CHATS_VIEW_TRACE,
            PermissionKey.CHATS_VIEW_COST_COLUMN,
        }
    ),
}


_CHAT_OWNER_GROUP_PERMISSION_BY_SLUG: dict[str, PermissionKey] = {
    SystemGroupSlug.USER.value: PermissionKey.CHATS_VIEW_USERS,
    SystemGroupSlug.ADMIN.value: PermissionKey.CHATS_VIEW_ADMINS,
    SystemGroupSlug.DEV.value: PermissionKey.CHATS_VIEW_DEVS,
}


def get_allowed_chat_owner_group_slugs(
    permission_map: Mapping[PermissionKey, bool],
) -> frozenset[str]:
    return frozenset(
        slug
        for slug, permission_key in _CHAT_OWNER_GROUP_PERMISSION_BY_SLUG.items()
        if permission_map.get(permission_key, False)
    )


def can_view_chat_owner(
    *, permission_map: Mapping[PermissionKey, bool], owner_group_slug: str | None, is_owner: bool
) -> bool:
    if is_owner and permission_map.get(PermissionKey.CHATS_VIEW_OWN, False):
        return True

    if owner_group_slug is None:
        return False

    permission_key = _CHAT_OWNER_GROUP_PERMISSION_BY_SLUG.get(owner_group_slug)
    if permission_key is None:
        return False

    return permission_map.get(permission_key, False)


def get_permission_definition_map() -> dict[PermissionKey, PermissionDefinition]:
    return {definition.key: definition for definition in PERMISSION_DEFINITIONS}


async def seed_system_groups(session: AsyncSession) -> dict[SystemGroupSlug, RbacGroup]:
    existing_groups = {
        group.slug: group
        for group in (
            await session.execute(
                select(RbacGroup).where(
                    RbacGroup.slug.in_([slug.value for slug, _ in SYSTEM_GROUP_SPECS])
                )
            )
        )
        .scalars()
        .all()
    }

    created = False
    for slug, description in SYSTEM_GROUP_SPECS:
        if slug.value in existing_groups:
            continue
        group = RbacGroup(slug=slug.value, name=slug.value, description=description, is_system=True)
        session.add(group)
        existing_groups[slug.value] = group
        created = True

    if created:
        await session.flush()

    for slug, _description in SYSTEM_GROUP_SPECS:
        group = existing_groups[slug.value]
        desired_keys = DEFAULT_GROUP_PERMISSIONS[slug]
        existing_keys = {
            row.permission_key
            for row in (
                await session.execute(
                    select(RbacGroupPermission).where(RbacGroupPermission.group_id == group.id)
                )
            )
            .scalars()
            .all()
        }
        missing_keys = desired_keys.difference(existing_keys)
        if missing_keys:
            session.add_all(
                RbacGroupPermission(group_id=group.id, permission_key=permission_key.value)
                for permission_key in sorted(missing_keys, key=lambda value: value.value)
            )

    await session.flush()
    return {slug: existing_groups[slug.value] for slug, _ in SYSTEM_GROUP_SPECS}


async def get_group_for_slug(session: AsyncSession, slug: SystemGroupSlug | str) -> RbacGroup:
    group_slug = slug.value if isinstance(slug, SystemGroupSlug) else slug
    group = await session.scalar(select(RbacGroup).where(RbacGroup.slug == group_slug))
    if group is None:
        raise RuntimeError(f"RBAC group '{group_slug}' is missing")
    return group


async def get_effective_permission_map(
    session: AsyncSession, user: User
) -> dict[PermissionKey, bool]:
    permission_map = dict.fromkeys(ALL_PERMISSION_KEYS, False)

    group_permission_rows = (
        (
            await session.execute(
                select(RbacGroupPermission.permission_key).where(
                    RbacGroupPermission.group_id == user.group_id
                )
            )
        )
        .scalars()
        .all()
    )
    for permission_key in group_permission_rows:
        try:
            permission_map[PermissionKey(permission_key)] = True
        except ValueError:
            continue

    user_override_rows = (
        await session.execute(
            select(
                RbacUserPermissionOverride.permission_key, RbacUserPermissionOverride.is_allowed
            ).where(RbacUserPermissionOverride.user_id == user.id)
        )
    ).all()
    for permission_key, is_allowed in user_override_rows:
        try:
            permission_map[PermissionKey(permission_key)] = bool(is_allowed)
        except ValueError:
            continue

    return permission_map


async def user_has_permission(
    session: AsyncSession, user: User, permission_key: PermissionKey
) -> bool:
    permission_map = await get_effective_permission_map(session, user)
    return permission_map.get(permission_key, False)


async def replace_group_permissions(
    session: AsyncSession, group: RbacGroup, permission_keys: set[PermissionKey]
) -> None:
    await session.execute(
        delete(RbacGroupPermission).where(RbacGroupPermission.group_id == group.id)
    )
    session.add_all(
        RbacGroupPermission(group_id=group.id, permission_key=permission_key.value)
        for permission_key in sorted(permission_keys, key=lambda value: value.value)
    )


async def replace_user_permission_overrides(
    session: AsyncSession, user: User, permission_overrides: dict[PermissionKey, bool | None]
) -> None:
    await session.execute(
        delete(RbacUserPermissionOverride).where(RbacUserPermissionOverride.user_id == user.id)
    )
    session.add_all(
        RbacUserPermissionOverride(
            user_id=user.id, permission_key=permission_key.value, is_allowed=is_allowed
        )
        for permission_key, is_allowed in sorted(
            permission_overrides.items(), key=lambda item: item[0].value
        )
        if is_allowed is not None
    )
