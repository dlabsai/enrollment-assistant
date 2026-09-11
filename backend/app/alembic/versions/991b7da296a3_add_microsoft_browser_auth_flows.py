"""add microsoft browser auth flows

Revision ID: 991b7da296a3
Revises: bba7c7bc7161
Create Date: 2026-09-11 16:10:25.625489

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "991b7da296a3"
down_revision: str | Sequence[str] | None = "bba7c7bc7161"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "microsoft_browser_auth_flow",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("flow", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("return_path", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_microsoft_browser_auth_flow_expires_at",
        "microsoft_browser_auth_flow",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_microsoft_browser_auth_flow_state_hash",
        "microsoft_browser_auth_flow",
        ["state_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_microsoft_browser_auth_flow_state_hash", table_name="microsoft_browser_auth_flow"
    )
    op.drop_index(
        "ix_microsoft_browser_auth_flow_expires_at", table_name="microsoft_browser_auth_flow"
    )
    op.drop_table("microsoft_browser_auth_flow")
