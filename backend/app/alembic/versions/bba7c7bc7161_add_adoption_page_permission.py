"""add adoption page permission

Revision ID: bba7c7bc7161
Revises: 0c31048e66cb
Create Date: 2026-08-17 16:31:15.703377

"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "bba7c7bc7161"
down_revision: str | None = "0c31048e66cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION_KEY = "access_adoption"
_GROUP_SLUGS: tuple[str, ...] = ("dev",)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    permission_table = sa.table(
        "rbac_group_permission",
        sa.column("id", sa.Uuid()),
        sa.column("group_id", sa.Uuid()),
        sa.column("permission_key", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    permission_rows: list[dict[str, object]] = []
    for slug in _GROUP_SLUGS:
        group_id = bind.execute(
            sa.text("SELECT id FROM rbac_group WHERE slug = :slug").bindparams(slug=slug)
        ).scalar_one_or_none()
        if group_id is None:
            continue

        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM rbac_group_permission "
                "WHERE group_id = :group_id AND permission_key = :permission_key"
            ).bindparams(group_id=group_id, permission_key=_PERMISSION_KEY)
        ).scalar_one_or_none()
        if exists is not None:
            continue

        permission_rows.append(
            {
                "id": uuid4(),
                "group_id": group_id,
                "permission_key": _PERMISSION_KEY,
                "created_at": now,
                "updated_at": now,
            }
        )

    if permission_rows:
        op.bulk_insert(permission_table, permission_rows)


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM rbac_group_permission "
            "WHERE permission_key = :permission_key "
            "AND group_id IN (SELECT id FROM rbac_group WHERE slug = ANY(:group_slugs))"
        ).bindparams(
            sa.bindparam("permission_key", value=_PERMISSION_KEY),
            sa.bindparam("group_slugs", value=list(_GROUP_SLUGS), type_=sa.ARRAY(sa.String())),
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM rbac_user_permission_override WHERE permission_key = :permission_key"
        ).bindparams(permission_key=_PERMISSION_KEY)
    )
