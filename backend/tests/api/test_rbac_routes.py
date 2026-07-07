from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import (
    DEFAULT_GROUP_PERMISSIONS,
    PermissionKey,
    SystemGroupSlug,
    get_group_for_slug,
)
from app.core.security import get_password_hash
from app.main import app
from app.models import User
from tests.api.auth_helpers import authenticate_client


async def _create_user(
    session: AsyncSession, *, group_slug: SystemGroupSlug, email_prefix: str
) -> User:
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        name=f"{group_slug.value.title()} User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def test_dev_group_defaults_include_message_footer_diagnostics() -> None:
    dev_permissions = DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.DEV]

    assert PermissionKey.CHAT_VIEW_RESPONSE_COST in dev_permissions
    assert PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES in dev_permissions
    assert (
        PermissionKey.CHAT_VIEW_RESPONSE_COST not in DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.USER]
    )
    assert (
        PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES
        not in DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.USER]
    )
    assert (
        PermissionKey.CHAT_VIEW_RESPONSE_COST
        not in DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.ADMIN]
    )
    assert (
        PermissionKey.CHAT_VIEW_GUARDRAILS_FAILURES
        not in DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.ADMIN]
    )


@pytest.mark.asyncio
async def test_rbac_group_updates_cannot_remove_last_access_rbac_user(
    transactional_session: AsyncSession,
) -> None:
    dev = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.DEV, email_prefix="rbac-dev"
    )
    dev_group = await get_group_for_slug(transactional_session, SystemGroupSlug.DEV)
    permission_keys = sorted(
        permission.value
        for permission in DEFAULT_GROUP_PERMISSIONS[SystemGroupSlug.DEV]
        if permission != PermissionKey.ACCESS_RBAC
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, dev.id)
        update_response = await client.put(
            f"/api/rbac/groups/{dev_group.id}/permissions",
            json={"permission_keys": permission_keys},
        )
        bootstrap_response = await client.get("/api/rbac/bootstrap")

    assert update_response.status_code == 400
    assert update_response.json() == {"detail": "At least one user must retain access_rbac access"}
    assert bootstrap_response.status_code == 200
