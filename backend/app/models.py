from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship

from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.utils import current_time_utc

if TYPE_CHECKING:
    from datetime import datetime


def _pascal_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _str_enum_values(enum: type[StrEnum]) -> list[str]:
    return [member.value for member in enum]


class Base(DeclarativeBase, AsyncAttrs):
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4, sort_order=-1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time_utc, sort_order=1
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time_utc, onupdate=current_time_utc, sort_order=1
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        return _pascal_to_snake(cls.__name__)


class EvalRunRecord(Base):
    report_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    suite: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    repeats: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_threshold: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    log_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_configs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    additional_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    cases: Mapped[list[EvalCaseResult]] = relationship(
        back_populates="eval_run", cascade="all, delete-orphan", order_by="EvalCaseResult.position"
    )


class EvalCaseResult(Base):
    eval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_run_record.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    eval_run: Mapped[EvalRunRecord] = relationship(back_populates="cases")
    runs: Mapped[list[EvalCaseRunResult]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="EvalCaseRunResult.run_index"
    )

    __table_args__ = (Index("ix_eval_case_result_run_position", "eval_run_id", "position"),)


class EvalCaseRunResult(Base):
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_case_result.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duration: Mapped[float] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    otel_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    otel_span_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    assertions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    case: Mapped[EvalCaseResult] = relationship(back_populates="runs")

    __table_args__ = (Index("ix_eval_case_run_result_case_run", "case_id", "run_index"),)


class EvalTestCaseOverlay(Base):
    suite: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    case_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_disk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_eval_test_case_overlay_suite_case", "suite", "case_id", unique=True),
    )


class OtelSpan(Base):
    trace_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)

    status_code: Mapped[str | None] = mapped_column(String, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    events: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    links: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    resource: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    span_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)

    request_model: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    provider_name: Mapped[str | None] = mapped_column(String, nullable=True)
    server_address: Mapped[str | None] = mapped_column(String, nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(nullable=True)

    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_embedding: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_internal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    conversation_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    message_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    total_time: Mapped[float | None] = mapped_column(nullable=True)


class Rating(StrEnum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


RatingEnum = SAEnum(
    Rating, values_callable=_str_enum_values, name="rating_enum", validate_strings=True
)


class RbacGroup(Base):
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="group")
    permissions: Mapped[list[RbacGroupPermission]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class RbacGroupPermission(Base):
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("rbac_group.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_key: Mapped[str] = mapped_column(String(128), nullable=False)

    group: Mapped[RbacGroup] = relationship(back_populates="permissions")

    __table_args__ = (
        Index(
            "ix_rbac_group_permission_group_permission", "group_id", "permission_key", unique=True
        ),
    )


class RbacUserPermissionOverride(Base):
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_key: Mapped[str] = mapped_column(String(128), nullable=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    user: Mapped[User] = relationship(back_populates="permission_overrides")

    __table_args__ = (
        Index(
            "ix_rbac_user_permission_override_user_permission",
            "user_id",
            "permission_key",
            unique=True,
        ),
    )


class User(Base):
    __table_args__ = (
        Index("ix_user_entra_identity", "entra_tenant_id", "entra_object_id", unique=True),
    )

    email: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    entra_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entra_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    group_id: Mapped[UUID] = mapped_column(ForeignKey("rbac_group.id"), nullable=False, index=True)

    group: Mapped[RbacGroup] = relationship(back_populates="users")
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="owner", cascade="all, delete"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    permission_overrides: Mapped[list[RbacUserPermissionOverride]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Conversation(Base):
    title: Mapped[str | None] = mapped_column(nullable=False)
    user: Mapped[bool] = mapped_column(default=False)
    project: Mapped[str] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="chat", nullable=False, index=True)
    investigation_source_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL"), nullable=True, index=True
    )
    investigation_source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("message.id", ondelete="SET NULL"), nullable=True, index=True
    )
    investigation_source_feedback_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("message_feedback.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
    )

    owner: Mapped[User | None] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Message.conversation_id",
    )
    feedback: Mapped[list[ConversationFeedback]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    public_contact: Mapped[PublicChatContact | None] = relationship(
        back_populates="conversation", uselist=False
    )


class PublicChatContact(Base):
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    zip_code: Mapped[str] = mapped_column("zip", String, nullable=False)
    visitor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL"), nullable=True
    )
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    environment: Mapped[str | None] = mapped_column(String, nullable=True)

    conversation: Mapped[Conversation | None] = relationship(back_populates="public_contact")

    __table_args__ = (
        Index("ix_public_chat_contact_conversation_unique", "conversation_id", unique=True),
        Index("ix_public_chat_contact_visitor_conversation", "visitor_id", "conversation_id"),
    )


class AssistantMessageMetadata(Base):
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    guardrails: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    system_prompt_rendered: Mapped[str] = mapped_column(nullable=False)
    conversation_turn: Mapped[int] = mapped_column(nullable=False)
    total_time: Mapped[float | None] = mapped_column(nullable=True)
    guardrail_model_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    guardrail_time: Mapped[float | None] = mapped_column(nullable=True)
    chatbot_times: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    guardrail_times: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    grounding_source_keys: Mapped[list[str | dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    grounding_source_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    message: Mapped[Message] = relationship(back_populates="assistant_message_metadata")


class Message(Base):
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("message.id"), nullable=True, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    guardrails_blocked: Mapped[bool] = mapped_column(default=False)
    guardrails_blocked_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_child_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("message.id"), nullable=True, index=True
    )

    parent: Mapped[Message | None] = relationship(
        "Message",
        remote_side="Message.id",
        foreign_keys="Message.parent_id",
        back_populates="children",
    )
    children: Mapped[list[Message]] = relationship(
        "Message",
        foreign_keys="Message.parent_id",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    active_child: Mapped[Message | None] = relationship(
        "Message", remote_side="Message.id", foreign_keys="Message.active_child_id"
    )
    conversation: Mapped[Conversation] = relationship(
        back_populates="messages", foreign_keys=[conversation_id]
    )
    feedback: Mapped[list[MessageFeedback]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    assistant_message_metadata: Mapped[AssistantMessageMetadata | None] = relationship(
        back_populates="message", cascade="all, delete-orphan", uselist=False
    )


class ConversationFeedback(Base):
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[Rating] = mapped_column(RatingEnum, nullable=False)
    text: Mapped[str | None] = mapped_column()

    conversation: Mapped[Conversation] = relationship(back_populates="feedback")
    user: Mapped[User] = relationship()


class MessageFeedback(Base):
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[Rating] = mapped_column(RatingEnum, nullable=False)
    text: Mapped[str | None] = mapped_column()

    message: Mapped[Message] = relationship(back_populates="feedback")
    user: Mapped[User] = relationship()


class DocumentType(StrEnum):
    WEBSITE_PAGE = "website_page"
    WEBSITE_PROGRAM = "website_program"
    CATALOG_PAGE = "catalog_page"
    CATALOG_PROGRAM = "catalog_program"
    CATALOG_COURSE = "catalog_course"
    TRAINING_MATERIAL = "training_material"


DocumentTypeEnum = SAEnum(
    DocumentType, values_callable=_str_enum_values, name="document_type_enum", validate_strings=True
)


class Document(Base):
    type: Mapped[DocumentType] = mapped_column(DocumentTypeEnum, nullable=False)
    id_: Mapped[int] = mapped_column(Integer, nullable=False)
    source_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    markdown_content: Mapped[str] = mapped_column(String, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    title_embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_VECTOR_DIMENSIONS), nullable=False
    )
    school: Mapped[str | None] = mapped_column(String, nullable=True)
    document_content_chunks: Mapped[list[DocumentContentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentContentChunk.sequence_number",
    )
    source_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    def embedding_content(self) -> str:
        return self.title

    __table_args__ = (
        Index(
            "idx_document_title_embedding",
            "title_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"title_embedding": "vector_l2_ops"},
        ),
    )


class RagDocumentExclusion(Base):
    source_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )


class RagDocumentExclusionEvent(Base):
    source_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    document_title: Mapped[str | None] = mapped_column(String, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (Index("ix_rag_document_exclusion_event_created_at", "created_at"),)


class DocumentContentChunk(Base):
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_VECTOR_DIMENSIONS), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document: Mapped[Document] = relationship(back_populates="document_content_chunks")

    def embedding_content(self) -> str:
        return self.content

    __table_args__ = (
        Index(
            "idx_document_content_chunk_content_embedding",
            "content_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"content_embedding": "vector_l2_ops"},
        ),
    )


class GuardrailUrlRegistry(Base):
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class RagBuildJob(Base):
    job_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    force_rebuild: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time_utc, nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_by: Mapped[User | None] = relationship(foreign_keys=[started_by_user_id])
    steps: Mapped[list[RagBuildJobStep]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="RagBuildJobStep.created_at"
    )
    source_stats: Mapped[list[RagBuildJobSourceStat]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="RagBuildJobSourceStat.source_name",
    )
    document_changes: Mapped[list[RagBuildJobDocumentChange]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_rag_build_job_status_started", "status", "started_at"),)


class RagBuildJobStep(Base):
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_build_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[RagBuildJob] = relationship(back_populates="steps")

    __table_args__ = (Index("ix_rag_build_job_step_job_key", "job_id", "step_key", unique=True),)


class RagBuildJobSourceStat(Base):
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_build_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    existing_document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped[RagBuildJob] = relationship(back_populates="source_stats")

    __table_args__ = (
        Index(
            "ix_rag_build_job_source_stat_unique",
            "job_id",
            "source_name",
            "document_type",
            unique=True,
        ),
    )


class RagBuildJobDocumentChange(Base):
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_build_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    previous_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    job: Mapped[RagBuildJob] = relationship(back_populates="document_changes")

    __table_args__ = (Index("ix_rag_build_job_document_change_job_type", "job_id", "change_type"),)


class PromptSetScope(StrEnum):
    ASSISTANT = "assistant"
    INVESTIGATION = "investigation"
    SUMMARY = "summary"
    TITLE = "title"
    TITLE_TRANSCRIPT = "title_transcript"
    GROUNDING = "grounding"


PromptSetScopeEnum = SAEnum(
    PromptSetScope, values_callable=_str_enum_values, name="prompt_set_scope", validate_strings=True
)


class PromptSetVersion(Base):
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    scope: Mapped[PromptSetScope] = mapped_column(
        PromptSetScopeEnum, default=PromptSetScope.ASSISTANT, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deployed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    prompts: Mapped[list[PromptSetTemplate]] = relationship(
        back_populates="prompt_set_version", cascade="all, delete-orphan"
    )


class PromptSetTemplate(Base):
    prompt_set_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_set_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    prompt_set_version: Mapped[PromptSetVersion] = relationship(back_populates="prompts")

    __table_args__ = (
        Index(
            "idx_prompt_set_template_version_filename",
            "prompt_set_version_id",
            "filename",
            unique=True,
        ),
    )
