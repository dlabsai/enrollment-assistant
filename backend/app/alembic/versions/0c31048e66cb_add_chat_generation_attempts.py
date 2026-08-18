"""add chat generation attempts

Revision ID: 0c31048e66cb
Revises: 41a1cd583fa6
Create Date: 2026-08-17 16:09:24.985497

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0c31048e66cb"
down_revision: str | None = "41a1cd583fa6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_generation_attempt",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["message.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["message.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_generation_attempt_user_id", "chat_generation_attempt", ["user_id"], unique=False
    )
    op.create_index(
        "ix_chat_generation_attempt_conversation_id",
        "chat_generation_attempt",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_generation_attempt_user_message_id",
        "chat_generation_attempt",
        ["user_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_generation_attempt_assistant_message_id",
        "chat_generation_attempt",
        ["assistant_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_generation_attempt_assistant_message_id", table_name="chat_generation_attempt"
    )
    op.drop_index(
        "ix_chat_generation_attempt_user_message_id", table_name="chat_generation_attempt"
    )
    op.drop_index(
        "ix_chat_generation_attempt_conversation_id", table_name="chat_generation_attempt"
    )
    op.drop_index("ix_chat_generation_attempt_user_id", table_name="chat_generation_attempt")
    op.drop_table("chat_generation_attempt")
