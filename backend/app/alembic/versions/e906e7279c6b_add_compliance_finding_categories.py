"""add compliance finding categories

Revision ID: e906e7279c6b
Revises: a43926318a9a
Create Date: 2026-10-01 12:25:54.562296

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e906e7279c6b"
down_revision: str | None = "a43926318a9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "compliance_finding",
        sa.Column("categories", postgresql.ARRAY(sa.String(length=40)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("compliance_finding", "categories")
