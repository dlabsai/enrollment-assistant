"""Add persistent eval run jobs and events.

Revision ID: 7a65dd08b6ce
Revises: q0r1s2t3u4v5
Create Date: 2026-07-16 19:38:56.423762
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "7a65dd08b6ce"
down_revision: str | None = "q0r1s2t3u4v5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_run_job",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("started_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("report_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["started_by_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_run_job_run_id", "eval_run_job", ["run_id"], unique=True)
    op.create_index(
        "ix_eval_run_job_started_by_user_id", "eval_run_job", ["started_by_user_id"], unique=False
    )
    op.create_index("ix_eval_run_job_suite", "eval_run_job", ["suite"], unique=False)
    op.create_index("ix_eval_run_job_status", "eval_run_job", ["status"], unique=False)
    op.create_index("ix_eval_run_job_report_id", "eval_run_job", ["report_id"], unique=False)
    op.create_index("ix_eval_run_job_started_at", "eval_run_job", ["started_at"], unique=False)
    op.create_index("ix_eval_run_job_heartbeat_at", "eval_run_job", ["heartbeat_at"], unique=False)
    op.create_index("ix_eval_run_job_completed_at", "eval_run_job", ["completed_at"], unique=False)
    op.create_index(
        "ix_eval_run_job_user_started",
        "eval_run_job",
        ["started_by_user_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "uq_eval_run_job_active_user",
        "eval_run_job",
        ["started_by_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('start', 'cancelling')"),
    )

    op.create_table(
        "eval_run_event",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["eval_run_job.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_run_event_sequence", "eval_run_event", ["sequence"], unique=True)
    op.create_index("ix_eval_run_event_run_id", "eval_run_event", ["run_id"], unique=False)
    op.create_index(
        "ix_eval_run_event_run_sequence", "eval_run_event", ["run_id", "sequence"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_eval_run_event_run_sequence", table_name="eval_run_event")
    op.drop_index("ix_eval_run_event_run_id", table_name="eval_run_event")
    op.drop_index("ix_eval_run_event_sequence", table_name="eval_run_event")
    op.drop_table("eval_run_event")

    op.drop_index("uq_eval_run_job_active_user", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_user_started", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_completed_at", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_heartbeat_at", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_started_at", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_report_id", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_status", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_suite", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_started_by_user_id", table_name="eval_run_job")
    op.drop_index("ix_eval_run_job_run_id", table_name="eval_run_job")
    op.drop_table("eval_run_job")
