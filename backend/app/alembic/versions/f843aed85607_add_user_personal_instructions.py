"""add user personal instructions

Revision ID: f843aed85607
Revises: cbb0a829944c
Create Date: 2026-10-01 12:45:00.000000

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f843aed85607"
down_revision: str | None = "cbb0a829944c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("personal_instructions", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("user", "personal_instructions")
