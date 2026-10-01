"""add_chat_insights

Revision ID: cbb0a829944c
Revises: 7eb570c49e74
Create Date: 2026-09-19 00:00:00.000000

"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "cbb0a829944c"
down_revision: str | Sequence[str] | None = "7eb570c49e74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = ("access_chat_insights", "run_chat_insights", "manage_chat_insight_categories")
_GROUP_SLUGS = ("admin", "dev")
_TOPICS = (
    (
        "Academic programs and courses",
        "Degrees, certificates, courses, curriculum, learning formats, program comparisons, "
        "and choosing an area of study.",
    ),
    (
        "Admissions and applications",
        "How to apply, general admission requirements, application materials, deadlines, "
        "decisions, and enrollment steps.",
    ),
    (
        "Tuition and financial aid",
        "Tuition, fees, payment options, scholarships, grants, loans, financial-aid "
        "applications, and general funding questions.",
    ),
    (
        "Transfer credit and student records",
        "Transfer-credit evaluation, transcripts, registration records, enrollment verification, "
        "diplomas, and student record updates.",
    ),
    (
        "Academic schedules and policies",
        "Academic calendars, term dates, course loads, add or drop rules, withdrawals, grades, "
        "academic standing, and degree progress.",
    ),
    (
        "Licensure and accreditation",
        "Institutional or program accreditation, professional licensure disclosures, "
        "certification considerations, and state authorization.",
    ),
    (
        "Student support and accessibility",
        "Academic support, accessibility accommodations, wellbeing resources, student services, "
        "and campus or online student life.",
    ),
    (
        "Career development",
        "Career exploration, internships, experiential learning, employment preparation, and "
        "career-service resources.",
    ),
    (
        "Technology help",
        "Student portals, learning platforms, account access, passwords, devices, uploads, and "
        "general technical support.",
    ),
    (
        "Military and veteran support",
        "Public information about education benefits, admissions support, transfer credit, and "
        "services for military-affiliated students.",
    ),
    (
        "Institutional information",
        "General information about the institution, locations, offices, contact channels, "
        "leadership, partnerships, and public services.",
    ),
    (
        "Other or unclear",
        "Empty, unclear, or out-of-scope chats that cannot be assigned to another topic.",
    ),
)


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")


def upgrade() -> None:
    op.create_table(
        "chat_insight_taxonomy_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("definitions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_insight_taxonomy_revision_number"),
        "chat_insight_taxonomy_revision",
        ["number"],
        unique=True,
    )
    op.create_index(
        op.f("ix_chat_insight_taxonomy_revision_status"),
        "chat_insight_taxonomy_revision",
        ["status"],
        unique=False,
    )
    op.create_table(
        "chat_insight_category",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=96), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("include_examples", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exclude_examples", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("origin", sa.String(length=24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_insight_category_key"), "chat_insight_category", ["key"], unique=True
    )

    op.create_table(
        "chat_insight_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("taxonomy_revision_id", sa.Uuid(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("full_backfill", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("classifier_version", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("eligible_chats", sa.Integer(), nullable=False),
        sa.Column("classified_chats", sa.Integer(), nullable=False),
        sa.Column("selected_grounding_answers", sa.Integer(), nullable=False),
        sa.Column("document_grounded_answers", sa.Integer(), nullable=False),
        sa.Column("referenced_documents", sa.Integer(), nullable=False),
        sa.Column("classified_documents", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("stability_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"], ["chat_insight_taxonomy_revision.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("status", "taxonomy_revision_id"):
        op.create_index(
            op.f(f"ix_chat_insight_run_{column}"), "chat_insight_run", [column], unique=False
        )
    op.create_index(
        "uq_chat_insight_run_active",
        "chat_insight_run",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "conversation_topic_classification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_revision_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("branch_hash", sa.String(length=64), nullable=False),
        sa.Column("classifier_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("primary_topic_key", sa.String(length=96), nullable=False),
        sa.Column("secondary_topic_keys", postgresql.ARRAY(sa.String(length=96)), nullable=False),
        sa.Column("request_type", sa.String(length=48), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["chat_insight_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"], ["chat_insight_taxonomy_revision.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_conversation_topic_revision",
        "conversation_topic_classification",
        ["conversation_id", "taxonomy_revision_id"],
        unique=True,
    )
    op.create_index(
        "ix_conversation_topic_revision_created",
        "conversation_topic_classification",
        ["taxonomy_revision_id", "source_created_at"],
        unique=False,
    )

    op.create_table(
        "grounding_document_reference",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_group", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("usage", sa.String(length=32), nullable=False),
        sa.Column("branch_hash", sa.String(length=64), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_protected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["message.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["chat_insight_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("conversation_id", "document_id", "selected_at"):
        op.create_index(
            op.f(f"ix_grounding_document_reference_{column}"),
            "grounding_document_reference",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_grounding_document_reference_message_source",
        "grounding_document_reference",
        ["assistant_message_id", "source_key"],
        unique=True,
    )
    op.create_index(
        "ix_grounding_document_reference_group_selected",
        "grounding_document_reference",
        ["source_group", "selected_at"],
        unique=False,
    )

    op.create_table(
        "grounding_document_classification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("classifier_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("primary_subject_key", sa.String(length=128), nullable=False),
        sa.Column(
            "secondary_subject_keys", postgresql.ARRAY(sa.String(length=128)), nullable=False
        ),
        sa.Column("document_function_key", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("evidence_basis", sa.String(length=48), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["chat_insight_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_grounding_document_classification_source_key"),
        "grounding_document_classification",
        ["source_key"],
        unique=True,
    )

    now = datetime.now(UTC)
    revision_id = uuid4()
    definitions: list[dict[str, object]] = [
        {"key": _key(name), "name": name, "description": description, "include": [], "exclude": []}
        for name, description in _TOPICS
    ]
    revision_table = sa.table(
        "chat_insight_taxonomy_revision",
        sa.column("id", sa.Uuid()),
        sa.column("number", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("definitions", postgresql.JSONB()),
        sa.column("created_by_user_id", sa.Uuid()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        revision_table,
        [
            {
                "id": revision_id,
                "number": 1,
                "status": "published",
                "definitions": definitions,
                "created_by_user_id": None,
                "published_at": now,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    category_table = sa.table(
        "chat_insight_category",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("include_examples", postgresql.JSONB()),
        sa.column("exclude_examples", postgresql.JSONB()),
        sa.column("origin", sa.String()),
        sa.column("active", sa.Boolean()),
        sa.column("created_by_user_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        category_table,
        [
            {
                "id": uuid4(),
                "key": _key(name),
                "name": name,
                "description": description,
                "include_examples": [],
                "exclude_examples": [],
                "origin": "system",
                "active": True,
                "created_by_user_id": None,
                "created_at": now,
                "updated_at": now,
            }
            for name, description in _TOPICS
        ],
    )

    permission_table = sa.table(
        "rbac_group_permission",
        sa.column("id", sa.Uuid()),
        sa.column("group_id", sa.Uuid()),
        sa.column("permission_key", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    permission_rows: list[dict[str, object]] = []
    bind = op.get_bind()
    for slug in _GROUP_SLUGS:
        group_id = bind.execute(
            sa.text("SELECT id FROM rbac_group WHERE slug = :slug").bindparams(slug=slug)
        ).scalar_one_or_none()
        if group_id is None:
            continue
        for permission_key in _PERMISSIONS:
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM rbac_group_permission "
                    "WHERE group_id = :group_id AND permission_key = :permission_key"
                ).bindparams(group_id=group_id, permission_key=permission_key)
            ).scalar_one_or_none()
            if exists is None:
                permission_rows.append(
                    {
                        "id": uuid4(),
                        "group_id": group_id,
                        "permission_key": permission_key,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
    if permission_rows:
        op.bulk_insert(permission_table, permission_rows)


def downgrade() -> None:
    for permission_key in _PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM rbac_user_permission_override WHERE permission_key = :permission_key"
            ).bindparams(permission_key=permission_key)
        )
        op.execute(
            sa.text(
                "DELETE FROM rbac_group_permission WHERE permission_key = :permission_key"
            ).bindparams(permission_key=permission_key)
        )

    op.drop_index(
        op.f("ix_grounding_document_classification_source_key"),
        table_name="grounding_document_classification",
    )
    op.drop_table("grounding_document_classification")

    op.drop_index(
        "ix_grounding_document_reference_group_selected", table_name="grounding_document_reference"
    )
    op.drop_index(
        "uq_grounding_document_reference_message_source", table_name="grounding_document_reference"
    )
    for column in ("selected_at", "document_id", "conversation_id"):
        op.drop_index(
            op.f(f"ix_grounding_document_reference_{column}"),
            table_name="grounding_document_reference",
        )
    op.drop_table("grounding_document_reference")

    op.drop_index(
        "ix_conversation_topic_revision_created", table_name="conversation_topic_classification"
    )
    op.drop_index("uq_conversation_topic_revision", table_name="conversation_topic_classification")
    op.drop_table("conversation_topic_classification")

    op.drop_index("uq_chat_insight_run_active", table_name="chat_insight_run")
    for column in ("taxonomy_revision_id", "status"):
        op.drop_index(op.f(f"ix_chat_insight_run_{column}"), table_name="chat_insight_run")
    op.drop_table("chat_insight_run")

    op.drop_index(op.f("ix_chat_insight_category_key"), table_name="chat_insight_category")
    op.drop_table("chat_insight_category")

    op.drop_index(
        op.f("ix_chat_insight_taxonomy_revision_status"),
        table_name="chat_insight_taxonomy_revision",
    )
    op.drop_index(
        op.f("ix_chat_insight_taxonomy_revision_number"),
        table_name="chat_insight_taxonomy_revision",
    )
    op.drop_table("chat_insight_taxonomy_revision")
