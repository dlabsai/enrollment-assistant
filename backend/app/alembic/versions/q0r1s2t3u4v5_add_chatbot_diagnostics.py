"""Add compact chatbot diagnostics to assistant metadata.

Revision ID: q0r1s2t3u4v5
Revises: p0q1r2s3t4u5
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "q0r1s2t3u4v5"
down_revision: str | None = "p0q1r2s3t4u5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_message_metadata",
        sa.Column("chatbot_model_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "assistant_message_metadata", sa.Column("chatbot_time", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("assistant_message_metadata", "chatbot_time")
    op.drop_column("assistant_message_metadata", "chatbot_model_settings")
