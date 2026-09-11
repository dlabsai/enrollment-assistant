"""add guardrail retry count

Revision ID: c6c2acd70ba3
Revises: 991b7da296a3
Create Date: 2026-09-11 16:22:21.187557

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection

revision: str = "c6c2acd70ba3"
down_revision: str | Sequence[str] | None = "991b7da296a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL_SQL = sa.text(
    """
    UPDATE assistant_message_metadata AS metadata
    SET guardrail_retry_count = CASE
        WHEN jsonb_typeof(metadata.guardrail_times) = 'array'
            THEN GREATEST(jsonb_array_length(metadata.guardrail_times) - 1, 0)
        WHEN jsonb_typeof(metadata.guardrails) = 'array'
            THEN GREATEST(
                jsonb_array_length(metadata.guardrails)
                - CASE WHEN message.guardrails_blocked THEN 1 ELSE 0 END,
                0
            )
        ELSE 0
    END
    FROM message
    WHERE message.id = metadata.message_id
    """
)


def backfill_guardrail_retry_counts(connection: Connection) -> None:
    connection.execute(_BACKFILL_SQL)


def upgrade() -> None:
    op.add_column(
        "assistant_message_metadata",
        sa.Column("guardrail_retry_count", sa.Integer(), nullable=True),
    )
    backfill_guardrail_retry_counts(op.get_bind())
    op.create_index(
        "ix_assistant_message_metadata_guardrail_retry_count",
        "assistant_message_metadata",
        ["guardrail_retry_count"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_message_metadata_guardrail_retry_count",
        table_name="assistant_message_metadata",
    )
    op.drop_column("assistant_message_metadata", "guardrail_retry_count")
