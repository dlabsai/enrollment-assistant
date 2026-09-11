"""Add reference-based compliance screening and scheduled service identity.

Revision ID: 581d5fbd700c
Revises: c6c2acd70ba3
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

revision: str = "581d5fbd700c"
down_revision: str | Sequence[str] | None = "c6c2acd70ba3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEDULER_USER_ID = UUID("0b93243a-4b25-412e-9c0a-6e79bbb64459")
_SCHEDULER_EMAIL = "screening-scheduler@system.invalid"


def _base() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _user(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"))


def upgrade() -> None:
    op.create_table(
        "compliance_instructions_version",
        *_base(),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("content", sa.Text(), nullable=False),
        _user("created_by_id"),
    )
    op.create_table(
        "compliance_screening",
        *_base(),
        _user("created_by_id"),
        sa.Column(
            "instructions_version_id",
            sa.Uuid(),
            sa.ForeignKey("compliance_instructions_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("screening_version", sa.String(32), nullable=False),
        sa.Column("model_settings", postgresql.JSONB(), nullable=False),
        sa.Column("admission_error_code", sa.String(40)),
    )
    op.create_table(
        "compliance_item",
        *_base(),
        sa.Column(
            "screening_id",
            sa.Uuid(),
            sa.ForeignKey("compliance_screening.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("message.id", ondelete="SET NULL")),
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("conversation.id", ondelete="SET NULL")
        ),
        _user("owner_id"),
        _user("requested_by_id"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("error_code", sa.String(40)),
    )
    for column in ("screening_id", "message_id", "conversation_id", "status"):
        op.create_index(f"ix_compliance_item_{column}", "compliance_item", [column])
    op.create_index(
        "ix_compliance_item_screening_message",
        "compliance_item",
        ["screening_id", "message_id"],
        unique=True,
    )
    op.create_table(
        "compliance_finding",
        *_base(),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("compliance_item.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id", sa.Uuid(), sa.ForeignKey("message.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_start", sa.Integer(), nullable=False),
        sa.Column("evidence_end", sa.Integer(), nullable=False),
        sa.Column("instruction_start", sa.Integer(), nullable=False),
        sa.Column("instruction_end", sa.Integer(), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("decision_revision", sa.Integer(), nullable=False),
    )
    for column in ("item_id", "message_id"):
        op.create_index(f"ix_compliance_finding_{column}", "compliance_finding", [column])
    op.create_table(
        "compliance_decision",
        *_base(),
        sa.Column(
            "finding_id",
            sa.Uuid(),
            sa.ForeignKey("compliance_finding.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _user("reviewer_id"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
    )
    op.create_index("ix_compliance_decision_finding_id", "compliance_decision", ["finding_id"])
    op.create_index(
        "ix_compliance_decision_revision",
        "compliance_decision",
        ["finding_id", "revision"],
        unique=True,
    )

    op.execute("""
        CREATE FUNCTION compliance_item_source_deleted() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.message_id IS NULL THEN
                NEW.status := 'deleted';
                NEW.conversation_id := NULL;
                NEW.input_hash := NULL;
                NEW.error_code := NULL;
                NEW.lease_token := NULL;
                NEW.leased_until := NULL;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER compliance_item_source_deleted
        BEFORE UPDATE ON compliance_item
        FOR EACH ROW EXECUTE FUNCTION compliance_item_source_deleted();
    """)
    # The OSS squash creates the RBAC schema without seed data. Ensure the
    # system groups exist so this migration also works on a fresh database.
    op.execute("""
        INSERT INTO rbac_group (
            id, slug, name, description, is_system, created_at, updated_at
        )
        VALUES
            (gen_random_uuid(), 'user', 'user', 'Standard staff access', true, now(), now()),
            (gen_random_uuid(), 'admin', 'admin', 'Administrative access', true, now(), now()),
            (gen_random_uuid(), 'dev', 'dev', 'Developer access', true, now(), now())
        ON CONFLICT (slug) DO NOTHING
    """)
    op.execute("""
        INSERT INTO rbac_group_permission (id, group_id, permission_key, created_at, updated_at)
        SELECT gen_random_uuid(), groups.id, permissions.key, now(), now()
        FROM rbac_group AS groups
        CROSS JOIN (VALUES ('access_compliance'), ('edit_compliance_instructions')) permissions(key)
        WHERE groups.slug = 'dev'
        ON CONFLICT DO NOTHING
    """)

    connection = op.get_bind()
    connection.execute(
        sa.text("""
            INSERT INTO "user" (
                id, email, name, password_hash, is_active, group_id, created_at, updated_at
            )
            SELECT :user_id, :email, 'Screening Scheduler', 'disabled-service-account',
                   true, id, now(), now()
            FROM rbac_group
            WHERE slug = 'user'
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                password_hash = EXCLUDED.password_hash,
                is_active = EXCLUDED.is_active,
                group_id = EXCLUDED.group_id,
                updated_at = EXCLUDED.updated_at
        """),
        {"user_id": _SCHEDULER_USER_ID, "email": _SCHEDULER_EMAIL},
    )
    connection.execute(
        sa.text("""
            INSERT INTO rbac_user_permission_override (
                id, user_id, permission_key, is_allowed, created_at, updated_at
            )
            SELECT permission.id, :user_id, permission.key, true, now(), now()
            FROM (
                VALUES
                    ('2be4ee63-4c21-4fd4-8a29-f9edc2aefb1b'::uuid, 'access_compliance'),
                    ('f0bf04c2-4d62-4e83-b6fb-2b135df72d32'::uuid, 'chats_view_users'),
                    ('37bec72b-bb3d-48ae-8322-7a7a0e5305aa'::uuid, 'chats_view_admins')
            ) AS permission(id, key)
        """),
        {"user_id": _SCHEDULER_USER_ID},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM rbac_user_permission_override WHERE user_id = :user_id"),
        {"user_id": _SCHEDULER_USER_ID},
    )
    connection.execute(
        sa.text('DELETE FROM "user" WHERE id = :user_id'), {"user_id": _SCHEDULER_USER_ID}
    )
    op.execute(
        "DELETE FROM rbac_group_permission "
        "WHERE permission_key IN ('access_compliance', 'edit_compliance_instructions')"
    )
    op.execute(
        "DELETE FROM rbac_user_permission_override "
        "WHERE permission_key IN ('access_compliance', 'edit_compliance_instructions')"
    )
    op.drop_table("compliance_decision")
    op.drop_table("compliance_finding")
    op.drop_table("compliance_item")
    op.execute("DROP FUNCTION compliance_item_source_deleted()")
    op.drop_table("compliance_screening")
    op.drop_table("compliance_instructions_version")
