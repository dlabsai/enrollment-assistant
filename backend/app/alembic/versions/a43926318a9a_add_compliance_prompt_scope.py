"""add compliance prompt scope

Revision ID: a43926318a9a
Revises: f217e562bd85
Create Date: 2026-10-01 12:25:10.642300

"""

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a43926318a9a"
down_revision: str | None = "f217e562bd85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE prompt_set_scope ADD VALUE IF NOT EXISTS 'compliance'")


def downgrade() -> None:
    # PostgreSQL enum values are intentionally not removed on downgrade.
    pass
