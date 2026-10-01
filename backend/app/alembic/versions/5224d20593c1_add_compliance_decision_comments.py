"""add compliance decision comments

Revision ID: 5224d20593c1
Revises: e906e7279c6b
Create Date: 2026-10-01 12:26:18.673566

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "5224d20593c1"
down_revision: str | None = "e906e7279c6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("compliance_decision", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("compliance_decision", "comment")
