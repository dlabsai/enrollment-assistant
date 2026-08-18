"""optimize review page indexes

Revision ID: 41a1cd583fa6
Revises: 7a65dd08b6ce
Create Date: 2026-08-17 15:38:11.614545

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "41a1cd583fa6"
down_revision: str | None = "7a65dd08b6ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These tables receive normal application writes, so avoid blocking them while
    # PostgreSQL builds the review-page indexes.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_message_conversation_created_at_desc",
            "message",
            ["conversation_id", sa.text("created_at DESC")],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_message_created_at_desc_id",
            "message",
            [sa.text("created_at DESC"), "id"],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_message_role_created_at_desc_id",
            "message",
            ["role", sa.text("created_at DESC"), "id"],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_otel_span_message_start_created_desc",
            "otel_span",
            ["message_id", sa.text("start_time DESC NULLS LAST"), sa.text("created_at DESC")],
            unique=False,
            postgresql_include=["trace_id", "span_id"],
            postgresql_where=sa.text("message_id IS NOT NULL"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_otel_span_conversation_trace",
            "otel_span",
            ["conversation_id", "trace_id"],
            unique=False,
            postgresql_where=sa.text("conversation_id IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_otel_span_conversation_trace", table_name="otel_span", postgresql_concurrently=True
        )
        op.drop_index(
            "ix_otel_span_message_start_created_desc",
            table_name="otel_span",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_message_role_created_at_desc_id", table_name="message", postgresql_concurrently=True
        )
        op.drop_index(
            "ix_message_created_at_desc_id", table_name="message", postgresql_concurrently=True
        )
        op.drop_index(
            "ix_message_conversation_created_at_desc",
            table_name="message",
            postgresql_concurrently=True,
        )
