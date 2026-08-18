"""Add conversation active root.

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "n9o0p1q2r3s4"
down_revision: str | None = "m8n9o0p1q2r3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("active_root_message_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE conversation
        SET active_root_message_id = (
            SELECT message.id
            FROM message
            WHERE message.conversation_id = conversation.id
              AND message.parent_id IS NULL
            ORDER BY message.created_at, message.id
            LIMIT 1
        )
        """
    )
    op.create_foreign_key(
        "fk_conversation_active_root_message_id_message",
        "conversation",
        "message",
        ["active_root_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_conversation_active_root_message_id"),
        "conversation",
        ["active_root_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_active_root_message_id"), table_name="conversation")
    op.drop_constraint(
        "fk_conversation_active_root_message_id_message", "conversation", type_="foreignkey"
    )
    op.drop_column("conversation", "active_root_message_id")
