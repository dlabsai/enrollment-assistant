"""Add conversation prompt context.

Revision ID: p0q1r2s3t4u5
Revises: o0p1q2r3s4t5
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "p0q1r2s3t4u5"
down_revision: str | None = "o0p1q2r3s4t5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("prompt_source", sa.String(length=32), nullable=True))
    op.add_column(
        "conversation",
        sa.Column("prompt_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_conversation_prompt_source", "conversation", ["prompt_source"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_prompt_source", table_name="conversation")
    op.drop_column("conversation", "prompt_context")
    op.drop_column("conversation", "prompt_source")
