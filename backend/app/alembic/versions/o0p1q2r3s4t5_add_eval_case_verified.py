"""Add eval case verified metadata.

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "o0p1q2r3s4t5"
down_revision: str | None = "n9o0p1q2r3s4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_test_case_overlay",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE eval_test_case_overlay
        SET verified = true
        WHERE case_data IS NOT NULL AND case_data ->> 'verified' = 'true'
        """
    )
    op.alter_column("eval_test_case_overlay", "verified", server_default=None)


def downgrade() -> None:
    op.drop_column("eval_test_case_overlay", "verified")
