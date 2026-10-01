from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.api.grounding_agent import GROUNDING_SOURCE_STATUS_SELECTED
from app.api.message_sources import (
    MessageSourceUsed,
    filter_sources_by_keys,
    get_tool_sources_used_by_message_ids,
    grounding_selection_key,
    is_canned_response_source,
    message_source_type_value,
)
from app.chat.tree_utils import get_current_branch_path_from_messages
from app.core.config import settings
from app.core.db import async_session_factory
from app.models import (
    AssistantMessageMetadata,
    ChatInsightCategory,
    ChatInsightRun,
    ChatInsightTaxonomyRevision,
    Conversation,
    ConversationTopicClassification,
    Document,
    DocumentType,
    GroundingDocumentClassification,
    GroundingDocumentReference,
    Message,
    RbacGroup,
    User,
)
from app.utils import current_time_utc, logger

from .classifier import (
    ChatClassificationInput,
    ChatClassificationResult,
    DocumentClassificationInput,
    DocumentClassificationResult,
    classify_chats,
    classify_documents,
    scrub_chat_text,
)
from .taxonomy import (
    CLASSIFIER_VERSION,
    DOCUMENT_TAXONOMY_VERSION,
    TOPIC_TAXONOMY_VERSION,
    CategoryDefinition,
    category_key,
    definitions_from_snapshot,
    document_function_definitions,
    document_subject_definitions,
    document_taxonomy_guidance,
    topic_taxonomy_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

RUN_LEASE = timedelta(seconds=90)
RUN_HEARTBEAT_SECONDS = 20
MAX_RUN_ATTEMPTS = 3
ANCHOR_SAMPLE_HASH_THRESHOLD = 20
ANCHOR_SAMPLE_LIMIT = 50
_ADMISSION_LOCK = 20_260_919_01


class CategoryConflictError(Exception):
    pass


class CategoryNotEditableError(Exception):
    pass


@dataclass(frozen=True)
class RunAdmission:
    run: ChatInsightRun
    created: bool


@dataclass(frozen=True)
class RunClaim:
    run_id: UUID
    token: UUID


@dataclass(frozen=True)
class SourceDocument:
    id: UUID
    source_key: str
    title: str
    url: str
    markdown_content: str


@dataclass(frozen=True)
class ReferenceInput:
    assistant_message_id: UUID
    conversation_id: UUID
    document_id: UUID | None
    source_key: str
    source_type: str
    source_group: str
    title: str
    url: str
    usage: str
    branch_hash: str
    selected_at: datetime
    is_protected: bool


@dataclass(frozen=True)
class PreparedRun:
    definitions: tuple[CategoryDefinition, ...]
    chat_classifier_fingerprint: str
    document_classifier_fingerprint: str
    all_chats: tuple[ChatClassificationInput, ...]
    pending_chats: tuple[ChatClassificationInput, ...]
    references: tuple[ReferenceInput, ...]
    stale_reference_ids: tuple[UUID, ...]
    eligible_conversation_ids: tuple[UUID, ...]
    all_documents: tuple[DocumentClassificationInput, ...]
    pending_documents: tuple[DocumentClassificationInput, ...]
    existing_chats: dict[UUID, ConversationTopicClassification]
    existing_documents: dict[str, GroundingDocumentClassification]
    selected_grounding_answers: int


def source_group(document_type: str) -> str:
    if document_type == DocumentType.TRAINING_MATERIAL.value:
        return "training_materials"
    if document_type in {
        DocumentType.WEBSITE_PAGE.value,
        DocumentType.WEBSITE_PROGRAM.value,
        DocumentType.CATALOG_PAGE.value,
        DocumentType.CATALOG_PROGRAM.value,
        DocumentType.CATALOG_COURSE.value,
    }:
        return "website_content"
    raise ValueError(f"Unknown grounding document type: {document_type}")


def _active_branch_hash(messages: Sequence[Message]) -> str:
    payload = [
        {
            "id": str(message.id),
            "parent_id": str(message.parent_id) if message.parent_id else None,
            "role": message.role,
            "content": message.content,
        }
        for message in messages
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _current_branch(
    messages: Sequence[Message], active_root_message_id: UUID | None
) -> list[Message]:
    messages_by_id = {message.id: message for message in messages}
    path = get_current_branch_path_from_messages(list(messages), active_root_message_id)
    return [messages_by_id[message_id] for message_id in path]


def _limited_user_messages(messages: Sequence[Message]) -> tuple[str, ...]:
    remaining = settings.CHAT_INSIGHTS_MAX_INPUT_CHARACTERS
    result: list[str] = []
    for message in messages:
        if message.role != "user" or remaining <= 0:
            continue
        content = message.content[:remaining]
        result.append(content)
        remaining -= len(content)
    return tuple(result)


def _chat_input_hash(user_messages: Sequence[str]) -> str:
    payload = [scrub_chat_text(message) for message in user_messages]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def trace_source_key(*, source_type: str, source_id: int, title: str, url: str) -> str:
    if source_type == DocumentType.TRAINING_MATERIAL.value and title.strip():
        return f"training_material:{title.strip().lstrip('/')}"
    del title, url
    return f"{source_type}:{source_id}"


def classifier_fingerprint(
    *,
    kind: str,
    model_name: str,
    classifier_version: str,
    definitions: Sequence[CategoryDefinition],
) -> str:
    taxonomy_version = TOPIC_TAXONOMY_VERSION if kind == "chat" else DOCUMENT_TAXONOMY_VERSION
    payload: dict[str, object] = {
        "classifier_version": classifier_version,
        "kind": kind,
        "model_name": model_name,
        "taxonomy_version": taxonomy_version,
        "definitions": [definition.as_dict() for definition in definitions],
    }
    if kind == "document":
        payload["guidance"] = list(document_taxonomy_guidance())
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _document_input_hash(
    *, source_type: str, title: str, url: str, evidence_basis: str, evidence: str
) -> str:
    payload = {
        "source_type": source_type,
        "title": title,
        "url": url,
        "evidence_basis": evidence_basis,
        "evidence": evidence,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _document_evidence(content: str, snippets: Sequence[str]) -> tuple[str, str]:
    clean_snippets = [" ".join(snippet.split()) for snippet in snippets if snippet.strip()]
    clean_content = content.strip()
    if clean_content and clean_snippets:
        basis = "document content and grounding excerpts"
    elif clean_content:
        basis = "document content"
    elif clean_snippets:
        basis = "grounding excerpts"
    else:
        basis = "title and metadata only"
    parts: list[str] = []
    if clean_snippets:
        parts.append("Grounding excerpts: " + " ".join(clean_snippets[:2])[:900])
    if clean_content:
        parts.append("Document excerpt: " + clean_content[:1100])
    return basis, "\n".join(parts)[:2000]


async def active_taxonomy_revision(session: AsyncSession) -> ChatInsightTaxonomyRevision:
    revision = await session.scalar(
        select(ChatInsightTaxonomyRevision)
        .where(ChatInsightTaxonomyRevision.status == "published")
        .order_by(ChatInsightTaxonomyRevision.number.desc())
        .limit(1)
    )
    if revision is None:
        raise RuntimeError("No published chat-insight taxonomy revision exists")
    return revision


async def _target_taxonomy_revision(session: AsyncSession) -> ChatInsightTaxonomyRevision:
    pending = await session.scalar(
        select(ChatInsightTaxonomyRevision)
        .where(ChatInsightTaxonomyRevision.status == "pending")
        .order_by(ChatInsightTaxonomyRevision.number.desc())
        .limit(1)
    )
    return pending or await active_taxonomy_revision(session)


async def _acquire_admission_lock(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _ADMISSION_LOCK}
    )


async def admit_run(
    session: AsyncSession,
    *,
    trigger: str,
    requested_by_user_id: UUID | None,
    cutoff_at: datetime | None = None,
) -> RunAdmission:
    await _acquire_admission_lock(session)
    existing = await session.scalar(
        select(ChatInsightRun)
        .where(ChatInsightRun.status.in_(["queued", "running"]))
        .order_by(ChatInsightRun.created_at)
        .limit(1)
    )
    if existing is not None:
        return RunAdmission(run=existing, created=False)
    revision = await _target_taxonomy_revision(session)
    run = ChatInsightRun(
        trigger=trigger,
        status="queued",
        requested_by_user_id=requested_by_user_id,
        taxonomy_revision_id=revision.id,
        cutoff_at=cutoff_at or current_time_utc(),
        full_backfill=revision.status == "pending",
        model_name=settings.CHAT_INSIGHTS_MODEL,
        classifier_version=CLASSIFIER_VERSION,
    )
    session.add(run)
    await session.flush()
    return RunAdmission(run=run, created=True)


async def claim_next_run(session: AsyncSession) -> RunClaim | None:
    now = current_time_utc()
    run = await session.scalar(
        select(ChatInsightRun)
        .where(
            or_(
                ChatInsightRun.status == "queued",
                (ChatInsightRun.status == "running") & (ChatInsightRun.leased_until < now),
            )
        )
        .order_by(ChatInsightRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    if run.attempts >= MAX_RUN_ATTEMPTS:
        run.status = "failed"
        run.finished_at = now
        run.leased_until = None
        run.lease_token = None
        run.error_code = "worker_interrupted"
        return None
    token = uuid4()
    run.status = "running"
    run.classifier_version = CLASSIFIER_VERSION
    run.started_at = run.started_at or now
    run.leased_until = now + RUN_LEASE
    run.lease_token = token
    run.attempts += 1
    return RunClaim(run_id=run.id, token=token)


async def _eligible_conversations(session: AsyncSession, cutoff_at: datetime) -> list[Conversation]:
    return list(
        (
            await session.scalars(
                select(Conversation)
                .join(User, User.id == Conversation.user_id)
                .join(RbacGroup, RbacGroup.id == User.group_id)
                .where(
                    Conversation.created_at <= cutoff_at,
                    Conversation.is_public.is_(False),
                    Conversation.kind == "chat",
                    or_(
                        Conversation.prompt_source.is_(None), Conversation.prompt_source != "draft"
                    ),
                    RbacGroup.slug.in_(["user", "admin"]),
                )
                .order_by(Conversation.created_at, Conversation.id)
            )
        ).all()
    )


async def _tool_sources(
    session: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[MessageSourceUsed]]:
    combined: dict[UUID, list[MessageSourceUsed]] = {}
    for index in range(0, len(message_ids), 100):
        batch = message_ids[index : index + 100]
        resolved = await get_tool_sources_used_by_message_ids(session, batch)
        combined.update(resolved)
    return combined


async def prepare_run(session: AsyncSession, run: ChatInsightRun) -> PreparedRun:
    revision = await session.get(ChatInsightTaxonomyRevision, run.taxonomy_revision_id)
    if revision is None:
        raise RuntimeError("Chat-insight taxonomy revision disappeared")
    definitions = definitions_from_snapshot(revision.definitions)
    chat_fingerprint = classifier_fingerprint(
        kind="chat",
        model_name=run.model_name,
        classifier_version=run.classifier_version,
        definitions=definitions,
    )
    document_definitions = (*document_subject_definitions(), *document_function_definitions())
    document_fingerprint = classifier_fingerprint(
        kind="document",
        model_name=run.model_name,
        classifier_version=run.classifier_version,
        definitions=document_definitions,
    )
    conversations = await _eligible_conversations(session, run.cutoff_at)
    conversation_ids = [conversation.id for conversation in conversations]
    message_rows = (
        list(
            (
                await session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id.in_(conversation_ids),
                        Message.created_at <= run.cutoff_at,
                    )
                    .order_by(Message.conversation_id, Message.created_at, Message.id)
                )
            ).all()
        )
        if conversation_ids
        else []
    )
    messages_by_conversation: dict[UUID, list[Message]] = defaultdict(list)
    for message in message_rows:
        messages_by_conversation[message.conversation_id].append(message)

    existing_chat_rows = (
        list(
            (
                await session.scalars(
                    select(ConversationTopicClassification).where(
                        ConversationTopicClassification.taxonomy_revision_id == revision.id,
                        ConversationTopicClassification.conversation_id.in_(conversation_ids),
                    )
                )
            ).all()
        )
        if conversation_ids
        else []
    )
    existing_chats = {row.conversation_id: row for row in existing_chat_rows}

    branches: dict[UUID, list[Message]] = {}
    branch_hashes: dict[UUID, str] = {}
    all_chats: list[ChatClassificationInput] = []
    pending_chats: list[ChatClassificationInput] = []
    for conversation in conversations:
        branch = _current_branch(
            messages_by_conversation.get(conversation.id, []), conversation.active_root_message_id
        )
        branches[conversation.id] = branch
        user_messages = _limited_user_messages(branch)
        input_hash = _chat_input_hash(user_messages)
        branch_hashes[conversation.id] = _active_branch_hash(branch)
        item = ChatClassificationInput(
            conversation_id=conversation.id,
            created_at=conversation.created_at,
            branch_hash=input_hash,
            user_messages=user_messages,
        )
        all_chats.append(item)
        existing = existing_chats.get(conversation.id)
        if (
            run.full_backfill
            or existing is None
            or existing.branch_hash != input_hash
            or existing.classifier_fingerprint != chat_fingerprint
        ):
            pending_chats.append(item)

    assistant_messages = {
        message.id: message
        for conversation_id, branch in branches.items()
        for message in branch
        if message.role == "assistant" and conversation_id in branch_hashes
    }
    metadata_rows = (
        list(
            (
                await session.scalars(
                    select(AssistantMessageMetadata).where(
                        AssistantMessageMetadata.message_id.in_(assistant_messages)
                    )
                )
            ).all()
        )
        if assistant_messages
        else []
    )
    metadata_by_message = {metadata.message_id: metadata for metadata in metadata_rows}
    selected_metadata = {
        message_id: metadata
        for message_id, metadata in metadata_by_message.items()
        if metadata.grounding_source_status == GROUNDING_SOURCE_STATUS_SELECTED
    }
    tool_sources = await _tool_sources(session, list(selected_metadata))

    selected_by_message: dict[UUID, list[MessageSourceUsed]] = {}
    replace_reference_message_ids = set(assistant_messages) - set(selected_metadata)
    selected_grounding_answers = 0
    for message_id, metadata in selected_metadata.items():
        selections = metadata.grounding_source_keys or []
        if selections:
            selected_grounding_answers += 1
        selected = filter_sources_by_keys(tool_sources.get(message_id, []), selections)
        requested_keys = {
            key
            for selection in selections
            if (key := grounding_selection_key(selection)) is not None
        }
        resolved_keys = {source.key for source in selected}
        if requested_keys <= resolved_keys:
            replace_reference_message_ids.add(message_id)
        if selected:
            selected_by_message[message_id] = selected

    selected_source_keys = {
        trace_source_key(
            source_type=message_source_type_value(source.type),
            source_id=source.id,
            title=source.title,
            url=source.url,
        )
        for selected in selected_by_message.values()
        for source in selected
        if not is_canned_response_source(source)
        and isinstance(source.type, DocumentType)
        and not source.identity_from_current_document
    }
    documents: list[SourceDocument] = []
    if selected_source_keys:
        document_rows = (
            await session.execute(
                select(
                    Document.id,
                    Document.source_key,
                    Document.title,
                    Document.url,
                    Document.markdown_content,
                ).where(Document.source_key.in_(selected_source_keys))
            )
        ).all()
        documents = [
            SourceDocument(
                id=row.id,
                source_key=row.source_key,
                title=row.title,
                url=row.url,
                markdown_content=row.markdown_content,
            )
            for row in document_rows
        ]
    document_by_source_key = {document.source_key: document for document in documents}

    references: list[ReferenceInput] = []
    evidence_snippets: dict[str, list[str]] = defaultdict(list)
    identity_data: dict[str, tuple[str, str, str, SourceDocument | None]] = {}
    for message_id, selected in selected_by_message.items():
        message = assistant_messages[message_id]
        seen: set[str] = set()
        for source_value in selected:
            if is_canned_response_source(source_value):
                continue
            source_type_value = message_source_type_value(source_value.type)
            identity_unverified = source_value.identity_from_current_document
            candidate_key = (
                "historical-unverified:"
                f"{source_type_value}:{source_value.id}:"
                f"{hashlib.sha256(source_value.key.encode()).hexdigest()[:24]}"
                if identity_unverified
                else trace_source_key(
                    source_type=source_type_value,
                    source_id=source_value.id,
                    title=source_value.title,
                    url=source_value.url,
                )
            )
            current_document = (
                document_by_source_key.get(candidate_key)
                if isinstance(source_value.type, DocumentType) and not identity_unverified
                else None
            )
            source_key = candidate_key
            if source_key in seen:
                continue
            seen.add(source_key)
            references.append(
                ReferenceInput(
                    assistant_message_id=message_id,
                    conversation_id=message.conversation_id,
                    document_id=current_document.id if current_document else None,
                    source_key=source_key,
                    source_type=source_type_value,
                    source_group=source_group(source_type_value),
                    title=(
                        f"Historical {source_type_value} source {source_value.id}"
                        if identity_unverified
                        else source_value.title
                    ),
                    url="" if identity_unverified else source_value.url,
                    usage=source_value.usage,
                    branch_hash=branch_hashes[message.conversation_id],
                    selected_at=message.created_at,
                    is_protected=False,
                )
            )
            if source_value.chunk:
                evidence_snippets[source_key].append(source_value.chunk)
            if not identity_unverified:
                identity_data[source_key] = (
                    source_type_value,
                    current_document.title if current_document else source_value.title,
                    current_document.url if current_document else source_value.url,
                    current_document,
                )

    existing_reference_rows: list[tuple[UUID, UUID]] = (
        list(
            (
                await session.execute(
                    select(
                        GroundingDocumentReference.id,
                        GroundingDocumentReference.assistant_message_id,
                    ).where(GroundingDocumentReference.conversation_id.in_(conversation_ids))
                )
            ).tuples()
        )
        if conversation_ids
        else []
    )
    active_assistant_ids = set(assistant_messages)
    stale_reference_ids = tuple(
        reference_id
        for reference_id, message_id in existing_reference_rows
        if message_id not in active_assistant_ids or message_id in replace_reference_message_ids
    )

    all_documents: list[DocumentClassificationInput] = []
    for source_key, (source_type_value, title, url, current_document) in identity_data.items():
        content = current_document.markdown_content if current_document else ""
        basis, evidence = _document_evidence(content, evidence_snippets[source_key])
        all_documents.append(
            DocumentClassificationInput(
                source_key=source_key,
                source_type=source_type_value,
                title=title,
                url=url,
                content_hash=_document_input_hash(
                    source_type=source_type_value,
                    title=title,
                    url=url,
                    evidence_basis=basis,
                    evidence=evidence,
                ),
                evidence_basis=basis,
                evidence=evidence,
            )
        )
    source_keys = [document.source_key for document in all_documents]
    existing_document_rows = (
        list(
            (
                await session.scalars(
                    select(GroundingDocumentClassification).where(
                        GroundingDocumentClassification.source_key.in_(source_keys)
                    )
                )
            ).all()
        )
        if source_keys
        else []
    )
    existing_documents = {row.source_key: row for row in existing_document_rows}
    pending_documents = [
        document
        for document in all_documents
        if document.source_key not in existing_documents
        or existing_documents[document.source_key].content_hash != document.content_hash
        or existing_documents[document.source_key].classifier_fingerprint != document_fingerprint
    ]
    return PreparedRun(
        definitions=definitions,
        chat_classifier_fingerprint=chat_fingerprint,
        document_classifier_fingerprint=document_fingerprint,
        all_chats=tuple(all_chats),
        pending_chats=tuple(pending_chats),
        references=tuple(references),
        stale_reference_ids=stale_reference_ids,
        eligible_conversation_ids=tuple(conversation_ids),
        all_documents=tuple(all_documents),
        pending_documents=tuple(pending_documents),
        existing_chats=existing_chats,
        existing_documents=existing_documents,
        selected_grounding_answers=selected_grounding_answers,
    )


def _anchor_sample[T](rows: Sequence[T], identity: Callable[[T], object]) -> list[T]:
    selected = [
        row
        for row in rows
        if hashlib.sha256(str(identity(row)).encode()).digest()[0] < ANCHOR_SAMPLE_HASH_THRESHOLD
    ]
    return selected[:ANCHOR_SAMPLE_LIMIT]


def _stability_metrics(
    prepared: PreparedRun,
    primary_chats: dict[UUID, ChatClassificationResult],
    review_chats: Sequence[ChatClassificationResult],
    primary_documents: dict[str, DocumentClassificationResult],
    review_documents: Sequence[DocumentClassificationResult],
) -> dict[str, object]:
    exact_topics = 0
    compatible_topics = 0
    compared_chats = 0
    for review in review_chats:
        primary = primary_chats.get(review.conversation_id)
        if primary is None:
            existing = prepared.existing_chats.get(review.conversation_id)
            if (
                existing is None
                or existing.branch_hash != review.branch_hash
                or existing.classifier_fingerprint != prepared.chat_classifier_fingerprint
            ):
                continue
            primary_topics = {existing.primary_topic_key, *existing.secondary_topic_keys}
            primary_topic = existing.primary_topic_key
        else:
            primary_topics = {primary.primary_topic_key, *primary.secondary_topic_keys}
            primary_topic = primary.primary_topic_key
        review_topics = {review.primary_topic_key, *review.secondary_topic_keys}
        exact_topics += int(primary_topic == review.primary_topic_key)
        compatible_topics += int(
            primary_topic == review.primary_topic_key
            or primary_topic in review_topics
            or review.primary_topic_key in primary_topics
        )
        compared_chats += 1

    exact_subjects = 0
    compatible_subjects = 0
    exact_functions = 0
    compared_documents = 0
    for review in review_documents:
        primary = primary_documents.get(review.source_key)
        if primary is None:
            existing_doc = prepared.existing_documents.get(review.source_key)
            if (
                existing_doc is None
                or existing_doc.content_hash != review.content_hash
                or existing_doc.classifier_fingerprint != prepared.document_classifier_fingerprint
            ):
                continue
            primary_subject = existing_doc.primary_subject_key
            primary_subjects = {
                existing_doc.primary_subject_key,
                *existing_doc.secondary_subject_keys,
            }
            primary_function = existing_doc.document_function_key
        else:
            primary_subject = primary.primary_subject_key
            primary_subjects = {primary.primary_subject_key, *primary.secondary_subject_keys}
            primary_function = primary.document_function_key
        review_subjects = {review.primary_subject_key, *review.secondary_subject_keys}
        exact_subjects += int(primary_subject == review.primary_subject_key)
        compatible_subjects += int(
            primary_subject == review.primary_subject_key
            or primary_subject in review_subjects
            or review.primary_subject_key in primary_subjects
        )
        exact_functions += int(primary_function == review.document_function_key)
        compared_documents += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    topic_exact = ratio(exact_topics, compared_chats)
    topic_compatible = ratio(compatible_topics, compared_chats)
    subject_exact = ratio(exact_subjects, compared_documents)
    subject_compatible = ratio(compatible_subjects, compared_documents)
    function_exact = ratio(exact_functions, compared_documents)
    warning = any(
        value is not None and value < threshold
        for value, threshold in (
            (topic_exact, 0.75),
            (topic_compatible, 0.9),
            (subject_exact, 0.8),
            (subject_compatible, 0.9),
            (function_exact, 0.7),
        )
    )
    return {
        "chat_sample": compared_chats,
        "exact_primary_topic_agreement": topic_exact,
        "compatible_topic_agreement": topic_compatible,
        "document_sample": compared_documents,
        "exact_primary_subject_agreement": subject_exact,
        "compatible_subject_agreement": subject_compatible,
        "exact_document_function_agreement": function_exact,
        "warning": warning,
    }


async def reconcile_grounding_references(
    session: AsyncSession,
    *,
    run_id: UUID,
    eligible_conversation_ids: Sequence[UUID],
    stale_reference_ids: Sequence[UUID],
    references: Sequence[ReferenceInput],
    now: datetime,
) -> None:
    if eligible_conversation_ids:
        await session.execute(
            delete(GroundingDocumentReference).where(
                GroundingDocumentReference.conversation_id.not_in(eligible_conversation_ids)
            )
        )
    else:
        await session.execute(delete(GroundingDocumentReference))
    for index in range(0, len(stale_reference_ids), 1000):
        await session.execute(
            delete(GroundingDocumentReference).where(
                GroundingDocumentReference.id.in_(stale_reference_ids[index : index + 1000])
            )
        )
    for reference in references:
        statement = insert(GroundingDocumentReference).values(
            assistant_message_id=reference.assistant_message_id,
            conversation_id=reference.conversation_id,
            run_id=run_id,
            document_id=reference.document_id,
            source_key=reference.source_key,
            source_type=reference.source_type,
            source_group=reference.source_group,
            title=reference.title,
            url=reference.url,
            usage=reference.usage,
            branch_hash=reference.branch_hash,
            selected_at=reference.selected_at,
            is_protected=reference.is_protected,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["assistant_message_id", "source_key"],
                set_={
                    "conversation_id": reference.conversation_id,
                    "run_id": run_id,
                    "document_id": reference.document_id,
                    "source_type": reference.source_type,
                    "source_group": reference.source_group,
                    "title": reference.title,
                    "url": reference.url,
                    "usage": reference.usage,
                    "branch_hash": reference.branch_hash,
                    "selected_at": reference.selected_at,
                    "is_protected": reference.is_protected,
                    "updated_at": now,
                },
            )
        )


async def finish_run(
    session: AsyncSession,
    run: ChatInsightRun,
    prepared: PreparedRun,
    chat_results: Sequence[ChatClassificationResult],
    document_results: Sequence[DocumentClassificationResult],
    *,
    error_count: int,
    stability_metrics: dict[str, object],
) -> None:
    now = current_time_utc()
    revision = await session.get(ChatInsightTaxonomyRevision, run.taxonomy_revision_id)
    if revision is None:
        raise RuntimeError("Chat-insight taxonomy revision disappeared")
    if revision.status == "pending" and error_count:
        run.status = "completed_with_errors"
        run.error_code = "classification_batch_failed"
        run.finished_at = now
        run.leased_until = None
        run.lease_token = None
        run.eligible_chats = len(prepared.all_chats)
        run.classified_chats = 0
        run.selected_grounding_answers = prepared.selected_grounding_answers
        run.document_grounded_answers = 0
        run.referenced_documents = 0
        run.classified_documents = 0
        run.error_count = error_count
        run.stability_metrics = stability_metrics
        return

    chat_input_by_id = {item.conversation_id: item for item in prepared.all_chats}
    eligible_ids = list(chat_input_by_id)
    stale_classifications = delete(ConversationTopicClassification).where(
        ConversationTopicClassification.taxonomy_revision_id == run.taxonomy_revision_id
    )
    if eligible_ids:
        stale_classifications = stale_classifications.where(
            ConversationTopicClassification.conversation_id.not_in(eligible_ids)
        )
    await session.execute(stale_classifications)
    successful_chat_ids = {result.conversation_id for result in chat_results}
    failed_or_stale_chat_ids = {
        item.conversation_id for item in prepared.pending_chats
    } - successful_chat_ids
    if failed_or_stale_chat_ids:
        await session.execute(
            delete(ConversationTopicClassification).where(
                ConversationTopicClassification.taxonomy_revision_id == run.taxonomy_revision_id,
                ConversationTopicClassification.conversation_id.in_(failed_or_stale_chat_ids),
            )
        )
    for result in chat_results:
        item = chat_input_by_id[result.conversation_id]
        statement = insert(ConversationTopicClassification).values(
            conversation_id=result.conversation_id,
            taxonomy_revision_id=run.taxonomy_revision_id,
            run_id=run.id,
            branch_hash=result.branch_hash,
            classifier_fingerprint=prepared.chat_classifier_fingerprint,
            primary_topic_key=result.primary_topic_key,
            secondary_topic_keys=list(result.secondary_topic_keys),
            request_type=result.request_type,
            confidence=result.confidence,
            source_created_at=item.created_at,
            classified_at=now,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["conversation_id", "taxonomy_revision_id"],
                set_={
                    "run_id": run.id,
                    "branch_hash": result.branch_hash,
                    "classifier_fingerprint": prepared.chat_classifier_fingerprint,
                    "primary_topic_key": result.primary_topic_key,
                    "secondary_topic_keys": list(result.secondary_topic_keys),
                    "request_type": result.request_type,
                    "confidence": result.confidence,
                    "source_created_at": item.created_at,
                    "classified_at": now,
                    "updated_at": now,
                },
            )
        )

    await reconcile_grounding_references(
        session,
        run_id=run.id,
        eligible_conversation_ids=prepared.eligible_conversation_ids,
        stale_reference_ids=prepared.stale_reference_ids,
        references=prepared.references,
        now=now,
    )

    successful_document_keys = {result.source_key for result in document_results}
    failed_or_stale_document_keys = {
        item.source_key for item in prepared.pending_documents
    } - successful_document_keys
    if failed_or_stale_document_keys:
        await session.execute(
            delete(GroundingDocumentClassification).where(
                GroundingDocumentClassification.source_key.in_(failed_or_stale_document_keys)
            )
        )
    for result in document_results:
        statement = insert(GroundingDocumentClassification).values(
            source_key=result.source_key,
            run_id=run.id,
            content_hash=result.content_hash,
            classifier_fingerprint=prepared.document_classifier_fingerprint,
            primary_subject_key=result.primary_subject_key,
            secondary_subject_keys=list(result.secondary_subject_keys),
            document_function_key=result.document_function_key,
            confidence=result.confidence,
            evidence_basis=result.evidence_basis,
            classified_at=now,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["source_key"],
                set_={
                    "run_id": run.id,
                    "content_hash": result.content_hash,
                    "classifier_fingerprint": prepared.document_classifier_fingerprint,
                    "primary_subject_key": result.primary_subject_key,
                    "secondary_subject_keys": list(result.secondary_subject_keys),
                    "document_function_key": result.document_function_key,
                    "confidence": result.confidence,
                    "evidence_basis": result.evidence_basis,
                    "classified_at": now,
                    "updated_at": now,
                },
            )
        )

    classification_rows: list[tuple[UUID, str, str]] = (
        list(
            (
                await session.execute(
                    select(
                        ConversationTopicClassification.conversation_id,
                        ConversationTopicClassification.branch_hash,
                        ConversationTopicClassification.classifier_fingerprint,
                    ).where(
                        ConversationTopicClassification.taxonomy_revision_id
                        == run.taxonomy_revision_id,
                        ConversationTopicClassification.conversation_id.in_(eligible_ids),
                    )
                )
            ).tuples()
        )
        if eligible_ids
        else []
    )
    classified_count = sum(
        branch_hash == chat_input_by_id[conversation_id].branch_hash
        and fingerprint == prepared.chat_classifier_fingerprint
        for conversation_id, branch_hash, fingerprint in classification_rows
    )
    document_input_by_key = {item.source_key: item for item in prepared.all_documents}
    document_keys = list(document_input_by_key)
    document_classification_rows: list[tuple[str, str, str]] = (
        list(
            (
                await session.execute(
                    select(
                        GroundingDocumentClassification.source_key,
                        GroundingDocumentClassification.content_hash,
                        GroundingDocumentClassification.classifier_fingerprint,
                    ).where(GroundingDocumentClassification.source_key.in_(document_keys))
                )
            ).tuples()
        )
        if document_keys
        else []
    )
    classified_document_count = sum(
        content_hash == document_input_by_key[source_key].content_hash
        and fingerprint == prepared.document_classifier_fingerprint
        for source_key, content_hash, fingerprint in document_classification_rows
    )
    can_publish = (
        revision.status == "pending"
        and error_count == 0
        and classified_count == len(prepared.all_chats)
    )
    if can_publish:
        await session.execute(
            update(ChatInsightTaxonomyRevision)
            .where(ChatInsightTaxonomyRevision.status == "published")
            .values(status="superseded", updated_at=now)
        )
        revision.status = "published"
        revision.published_at = now

    stability_warning = bool(stability_metrics.get("warning"))
    if error_count:
        run.status = "completed_with_errors"
        run.error_code = "classification_batch_failed"
    elif stability_warning:
        run.status = "completed_with_warnings"
        run.error_code = "stability_threshold"
    else:
        run.status = "completed"
        run.error_code = None
    run.finished_at = now
    run.leased_until = None
    run.lease_token = None
    run.eligible_chats = len(prepared.all_chats)
    run.classified_chats = classified_count
    run.selected_grounding_answers = prepared.selected_grounding_answers
    run.document_grounded_answers = int(
        await session.scalar(
            select(func.count(func.distinct(GroundingDocumentReference.assistant_message_id)))
        )
        or 0
    )
    run.referenced_documents = int(
        await session.scalar(
            select(func.count(func.distinct(GroundingDocumentReference.source_key)))
        )
        or 0
    )
    run.classified_documents = classified_document_count
    run.error_count = error_count
    run.stability_metrics = stability_metrics


def _claim_condition(claim: RunClaim) -> ColumnElement[bool]:
    return and_(
        ChatInsightRun.id == claim.run_id,
        ChatInsightRun.status == "running",
        ChatInsightRun.lease_token == claim.token,
    )


async def _execute_claim_work(claim: RunClaim) -> None:
    async with async_session_factory() as session:
        run = await session.scalar(select(ChatInsightRun).where(_claim_condition(claim)))
        if run is None:
            return
        prepared = await prepare_run(session, run)
        model_name = run.model_name
        await session.commit()

    chat_batch = await classify_chats(
        list(prepared.pending_chats),
        prepared.definitions,
        model_name=model_name,
        run_id=claim.run_id,
        stage="primary",
    )
    document_batch = await classify_documents(
        list(prepared.pending_documents),
        document_subject_definitions(),
        document_function_definitions(),
        model_name=model_name,
        run_id=claim.run_id,
        stage="primary",
    )
    primary_chats = {result.conversation_id: result for result in chat_batch.classifications}
    primary_documents = {result.source_key: result for result in document_batch.classifications}
    chat_anchor = _anchor_sample(prepared.all_chats, lambda item: item.conversation_id)
    document_anchor = _anchor_sample(prepared.all_documents, lambda item: item.source_key)
    review_chat_batch = await classify_chats(
        chat_anchor,
        prepared.definitions,
        model_name=model_name,
        run_id=claim.run_id,
        stage="stability",
    )
    review_document_batch = await classify_documents(
        document_anchor,
        document_subject_definitions(),
        document_function_definitions(),
        model_name=model_name,
        run_id=claim.run_id,
        stage="stability",
    )
    errors = (
        chat_batch.error_count
        + document_batch.error_count
        + review_chat_batch.error_count
        + review_document_batch.error_count
    )
    stability = _stability_metrics(
        prepared,
        primary_chats,
        review_chat_batch.classifications,
        primary_documents,
        review_document_batch.classifications,
    )
    async with async_session_factory() as session:
        run = await session.scalar(
            select(ChatInsightRun).where(_claim_condition(claim)).with_for_update()
        )
        if run is None:
            return
        await finish_run(
            session,
            run,
            prepared,
            chat_batch.classifications,
            document_batch.classifications,
            error_count=errors,
            stability_metrics=stability,
        )
        await session.commit()


async def _heartbeat[T](claim: RunClaim, lost: asyncio.Event, work_task: asyncio.Task[T]) -> None:
    while True:
        await asyncio.sleep(RUN_HEARTBEAT_SECONDS)
        try:
            async with async_session_factory() as session:
                renewed = await session.scalar(
                    update(ChatInsightRun)
                    .where(_claim_condition(claim))
                    .values(leased_until=current_time_utc() + RUN_LEASE)
                    .returning(ChatInsightRun.id)
                )
                await session.commit()
            if renewed is not None:
                continue
        except Exception:
            logger.warning("Chat-insight lease unavailable for run %s", claim.run_id, exc_info=True)
        lost.set()
        work_task.cancel()
        return


async def execute_run(claim: RunClaim) -> None:
    lost = asyncio.Event()
    work_task = asyncio.create_task(_execute_claim_work(claim))
    heartbeat = asyncio.create_task(_heartbeat(claim, lost, work_task))
    try:
        await work_task
    except asyncio.CancelledError:
        if lost.is_set():
            return
        raise
    except Exception:
        logger.exception("Chat-insight run %s failed", claim.run_id)
        async with async_session_factory() as session:
            await session.execute(
                update(ChatInsightRun)
                .where(_claim_condition(claim))
                .values(
                    status="failed",
                    finished_at=current_time_utc(),
                    leased_until=None,
                    lease_token=None,
                    error_code="run_failed",
                    error_count=ChatInsightRun.error_count + 1,
                )
            )
            await session.commit()
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def list_categories(session: AsyncSession) -> list[ChatInsightCategory]:
    return list(
        (
            await session.scalars(
                select(ChatInsightCategory).order_by(
                    ChatInsightCategory.active.desc(),
                    ChatInsightCategory.origin,
                    ChatInsightCategory.name,
                )
            )
        ).all()
    )


async def _category_name_conflicts(
    session: AsyncSession, *, name: str, exclude_id: UUID | None = None
) -> bool:
    normalized = category_key(name)
    rows = (
        await session.execute(
            select(ChatInsightCategory.id, ChatInsightCategory.key, ChatInsightCategory.name)
        )
    ).all()
    return any(
        category_id != exclude_id
        and (key == normalized or category_key(existing_name) == normalized)
        for category_id, key, existing_name in rows
    )


async def _queue_category_revision(
    session: AsyncSession, *, requested_by_user_id: UUID
) -> RunAdmission:
    await _acquire_admission_lock(session)
    pending = await session.scalar(
        select(ChatInsightTaxonomyRevision.id).where(
            ChatInsightTaxonomyRevision.status == "pending"
        )
    )
    active_run = await session.scalar(
        select(ChatInsightRun.id).where(ChatInsightRun.status.in_(["queued", "running"]))
    )
    if pending is not None or active_run is not None:
        raise CategoryConflictError("An analysis run or category backfill is already pending")
    active = [category for category in await list_categories(session) if category.active]
    next_number = (
        int(await session.scalar(select(func.max(ChatInsightTaxonomyRevision.number))) or 0) + 1
    )
    revision = ChatInsightTaxonomyRevision(
        number=next_number,
        status="pending",
        definitions=topic_taxonomy_snapshot(
            tuple(
                CategoryDefinition(
                    key=category.key,
                    name=category.name,
                    description=category.description,
                    include=tuple(category.include_examples),
                    exclude=tuple(category.exclude_examples),
                )
                for category in active
            )
        ),
        created_by_user_id=requested_by_user_id,
    )
    session.add(revision)
    await session.flush()
    return await admit_run(
        session, trigger="category_change", requested_by_user_id=requested_by_user_id
    )


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    include_examples: list[str],
    exclude_examples: list[str],
    requested_by_user_id: UUID,
) -> tuple[ChatInsightCategory, ChatInsightRun]:
    await _acquire_admission_lock(session)
    key = category_key(name)
    if await _category_name_conflicts(session, name=name):
        raise CategoryConflictError("A category with this name already exists")
    category = ChatInsightCategory(
        key=key,
        name=name.strip(),
        description=description.strip(),
        include_examples=include_examples,
        exclude_examples=exclude_examples,
        origin="client",
        active=True,
        created_by_user_id=requested_by_user_id,
    )
    session.add(category)
    await session.flush()
    admission = await _queue_category_revision(session, requested_by_user_id=requested_by_user_id)
    return category, admission.run


async def update_category(
    session: AsyncSession,
    *,
    category_key_value: str,
    name: str,
    description: str,
    include_examples: list[str],
    exclude_examples: list[str],
    active: bool,
    requested_by_user_id: UUID,
) -> tuple[ChatInsightCategory, ChatInsightRun | None]:
    await _acquire_admission_lock(session)
    category = await session.scalar(
        select(ChatInsightCategory)
        .where(ChatInsightCategory.key == category_key_value)
        .with_for_update()
    )
    if category is None:
        raise LookupError(category_key_value)
    if category.origin != "client":
        raise CategoryNotEditableError
    normalized_name = name.strip()
    normalized_description = description.strip()
    if await _category_name_conflicts(session, name=normalized_name, exclude_id=category.id):
        raise CategoryConflictError("A category with this name already exists")
    if (
        category.name == normalized_name
        and category.description == normalized_description
        and category.include_examples == include_examples
        and category.exclude_examples == exclude_examples
        and category.active == active
    ):
        return category, None
    category.name = normalized_name
    category.description = normalized_description
    category.include_examples = include_examples
    category.exclude_examples = exclude_examples
    category.active = active
    admission = await _queue_category_revision(session, requested_by_user_id=requested_by_user_id)
    return category, admission.run
