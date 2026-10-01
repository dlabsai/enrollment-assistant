from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.usage import UsageLimits

from app.chat.agents import get_pydantic_ai_model_name
from app.core.config import settings
from app.utils import logger

from .taxonomy import REQUEST_TYPES, CategoryDefinition, document_taxonomy_guidance

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)")
_LONG_NUMBER_RE = re.compile(r"\b\d{6,}\b")

Confidence = Literal["high", "medium", "low"]
ClassificationStage = Literal["primary", "stability"]


class ClassificationOutputError(ValueError):
    pass


class _NumberedAssignment(Protocol):
    item: int


@dataclass(frozen=True)
class ChatClassificationInput:
    conversation_id: UUID
    created_at: datetime
    branch_hash: str
    user_messages: tuple[str, ...]


@dataclass(frozen=True)
class DocumentClassificationInput:
    source_key: str
    source_type: str
    title: str
    url: str
    content_hash: str
    evidence_basis: str
    evidence: str


@dataclass(frozen=True)
class ChatClassificationResult:
    conversation_id: UUID
    branch_hash: str
    primary_topic_key: str
    secondary_topic_keys: tuple[str, ...]
    request_type: str
    confidence: Confidence


@dataclass(frozen=True)
class DocumentClassificationResult:
    source_key: str
    content_hash: str
    primary_subject_key: str
    secondary_subject_keys: tuple[str, ...]
    document_function_key: str
    confidence: Confidence
    evidence_basis: str


@dataclass(frozen=True)
class ChatBatchResult:
    classifications: tuple[ChatClassificationResult, ...]
    error_count: int


@dataclass(frozen=True)
class DocumentBatchResult:
    classifications: tuple[DocumentClassificationResult, ...]
    error_count: int


@dataclass(frozen=True)
class _ChatClassificationDeps:
    rows: tuple[ChatClassificationInput, ...]
    definitions: tuple[CategoryDefinition, ...]


@dataclass(frozen=True)
class _DocumentClassificationDeps:
    rows: tuple[DocumentClassificationInput, ...]
    subjects: tuple[CategoryDefinition, ...]
    functions: tuple[CategoryDefinition, ...]


def _exception_attribute(error: BaseException, name: str) -> object | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        value = getattr(current, name, None)
        if value is not None:
            return value
        current = current.__cause__ or current.__context__
    return None


def _log_classification_batch_failure(
    error: BaseException,
    *,
    run_id: UUID,
    kind: Literal["chat", "document"],
    stage: ClassificationStage,
    batch_number: int,
    batch_count: int,
    batch_size: int,
) -> None:
    logger.error(
        "Chat-insight classification batch failed "
        "run_id=%s kind=%s stage=%s batch=%s/%s batch_size=%s exception=%s status=%s "
        "request_id=%s",
        run_id,
        kind,
        stage,
        batch_number,
        batch_count,
        batch_size,
        type(error).__name__,
        _exception_attribute(error, "status_code"),
        _exception_attribute(error, "request_id"),
        exc_info=(type(error), error, error.__traceback__),
    )


class _ChatAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: int
    primary_topic: str
    secondary_topics: list[str] = Field(default_factory=list, max_length=2)
    request_type: str
    confidence: Confidence


class _ChatAssignmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[_ChatAssignment]


class _DocumentAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: int
    primary_subject: str
    secondary_subjects: list[str] = Field(default_factory=list, max_length=2)
    document_function: str
    confidence: Confidence


class _DocumentAssignmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[_DocumentAssignment]


def scrub_chat_text(value: str, *, limit: int = 1800) -> str:
    text = " ".join(value.split())
    text = _EMAIL_RE.sub("[email]", text)
    text = _URL_RE.sub("[url]", text)
    text = _PHONE_RE.sub("[phone]", text)
    text = _LONG_NUMBER_RE.sub("[number]", text)
    return text[:limit]


def _model_settings(model_name: str) -> OpenAIResponsesModelSettings:
    model_settings = OpenAIResponsesModelSettings(max_tokens=10000, openai_store=False)
    if "gpt-5" in model_name:
        model_settings["thinking"] = "low"
    else:
        model_settings["temperature"] = 0.0
    return model_settings


def _definition_prompt(definition: CategoryDefinition) -> str:
    parts = [f"- key={definition.key}; name={definition.name}; definition={definition.description}"]
    if definition.include:
        parts.append("  Include: " + "; ".join(definition.include))
    if definition.exclude:
        parts.append("  Exclude: " + "; ".join(definition.exclude))
    return "\n".join(parts)


def build_chat_classification_prompt(
    rows: list[ChatClassificationInput], definitions: tuple[CategoryDefinition, ...]
) -> str:
    taxonomy = "\n".join(_definition_prompt(definition) for definition in definitions)
    chats = "\n\n".join(
        "\n".join(
            [
                f'<chat item="{index}">',
                *(
                    f"User turn {turn}: {scrub_chat_text(message)}"
                    for turn, message in enumerate(row.user_messages, 1)
                ),
                "</chat>",
            ]
        )
        for index, row in enumerate(rows, 1)
    )
    return f"""
Classify staff-authored messages from internal university-assistant chats.

For every chat:
- Choose exactly one primary topic key from the taxonomy.
- Add zero to two topic keys only for independently requested secondary subjects.
- Follow the category boundaries and classify only the user's underlying request.
- Choose exactly one request type from: {", ".join(REQUEST_TYPES)}.
- Confidence reflects clarity of the user messages, not confidence in university policy.
- Return every numbered item exactly once. Never return category display names in key fields.

Taxonomy:
{taxonomy}

Chats:
{chats}
""".strip()


def _document_prompt(
    rows: list[DocumentClassificationInput],
    subjects: tuple[CategoryDefinition, ...],
    functions: tuple[CategoryDefinition, ...],
) -> str:
    subject_text = "\n".join(_definition_prompt(definition) for definition in subjects)
    function_text = "\n".join(_definition_prompt(definition) for definition in functions)
    guidance = "\n".join(f"- {item}" for item in document_taxonomy_guidance())
    documents = "\n\n".join(
        "\n".join(
            [
                f'<document item="{index}">',
                f"Source type: {row.source_type}",
                f"Title: {row.title}",
                f"URL or source path: {row.url}",
                f"Evidence basis: {row.evidence_basis}",
                row.evidence or "No content excerpt is available.",
                "</document>",
            ]
        )
        for index, row in enumerate(rows, 1)
    )
    return f"""
Classify university knowledge documents selected as grounding for assistant answers.

For every document:
- Choose exactly one primary subject key and up to two substantial secondary subject keys.
- Choose exactly one document-function key. Function is purpose, not subject or source family.
- Exact reusable wording beats training; step-by-step execution beats overview; binding rules or
  disclosures beat procedure; rapid lookup tables beat general reference.
- Ignore dates, versions, file formats, names, and identifiers.
- Confidence reflects the supplied evidence. Return every item exactly once and use keys only.

Subject taxonomy:
{subject_text}

Function taxonomy:
{function_text}

Taxonomy guidance:
{guidance}

Documents:
{documents}
""".strip()


def _required_key(value: str, allowed: set[str], *, field: str) -> str:
    if value not in allowed:
        raise ClassificationOutputError(f"Invalid {field}: {value}")
    return value


def _validate_secondary_keys(
    values: list[str], *, allowed: set[str], primary: str, field: str
) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        key = _required_key(value, allowed, field=field)
        if key == primary:
            raise ClassificationOutputError(f"{field.title()} duplicates primary key: {key}")
        if key in normalized:
            raise ClassificationOutputError(f"Duplicate {field}: {key}")
        normalized.append(key)
    return tuple(normalized)


def _assignments_by_item[T: _NumberedAssignment](
    assignments: list[T], expected: int
) -> dict[int, T]:
    returned: dict[int, T] = {}
    for assignment in assignments:
        item = assignment.item
        if item < 1 or item > expected:
            raise ClassificationOutputError(f"Unexpected item number: {item}")
        if item in returned:
            raise ClassificationOutputError(f"Duplicate item number: {item}")
        returned[item] = assignment
    expected_items = set(range(1, expected + 1))
    if returned.keys() != expected_items:
        missing = sorted(expected_items - returned.keys())
        raise ClassificationOutputError(f"Missing item numbers: {missing}")
    return returned


def validate_chat_assignment_payload(
    rows: list[ChatClassificationInput],
    definitions: tuple[CategoryDefinition, ...],
    payload: object,
) -> tuple[ChatClassificationResult, ...]:
    output = _ChatAssignmentBatch.model_validate(payload)
    allowed = {definition.key for definition in definitions}
    returned = _assignments_by_item(output.assignments, len(rows))
    classifications: list[ChatClassificationResult] = []
    for index, row in enumerate(rows, 1):
        assignment = returned[index]
        primary = _required_key(assignment.primary_topic, allowed, field="primary topic")
        secondary = _validate_secondary_keys(
            assignment.secondary_topics, allowed=allowed, primary=primary, field="secondary topic"
        )
        if assignment.request_type not in REQUEST_TYPES:
            raise ClassificationOutputError(f"Invalid request type: {assignment.request_type}")
        classifications.append(
            ChatClassificationResult(
                conversation_id=row.conversation_id,
                branch_hash=row.branch_hash,
                primary_topic_key=primary,
                secondary_topic_keys=secondary,
                request_type=assignment.request_type,
                confidence=assignment.confidence,
            )
        )
    return tuple(classifications)


def _retry_invalid_chat_output(
    ctx: RunContext[_ChatClassificationDeps], output: _ChatAssignmentBatch
) -> _ChatAssignmentBatch:
    try:
        validate_chat_assignment_payload(list(ctx.deps.rows), ctx.deps.definitions, output)
    except ClassificationOutputError as exc:
        raise ModelRetry(
            f"{exc}. Topic fields must use taxonomy keys; request types belong only in "
            "request_type."
        ) from exc
    return output


async def _classify_chat_batch(
    agent: Agent[_ChatClassificationDeps, _ChatAssignmentBatch],
    rows: list[ChatClassificationInput],
    definitions: tuple[CategoryDefinition, ...],
    semaphore: asyncio.Semaphore,
    model_name: str,
) -> tuple[ChatClassificationResult, ...]:
    async with semaphore:
        result = await agent.run(
            build_chat_classification_prompt(rows, definitions),
            deps=_ChatClassificationDeps(rows=tuple(rows), definitions=definitions),
            model_settings=_model_settings(model_name),
            usage_limits=UsageLimits(request_limit=2),
        )
    return validate_chat_assignment_payload(rows, definitions, result.output)


async def classify_chats(
    rows: list[ChatClassificationInput],
    definitions: tuple[CategoryDefinition, ...],
    *,
    model_name: str,
    run_id: UUID,
    stage: ClassificationStage,
) -> ChatBatchResult:
    if not rows:
        return ChatBatchResult(classifications=(), error_count=0)
    allowed = {definition.key for definition in definitions}
    fallback = "other-or-unclear" if "other-or-unclear" in allowed else definitions[-1].key
    empty = [row for row in rows if not any(message.strip() for message in row.user_messages)]
    nonempty = [row for row in rows if row not in empty]
    classifications = [
        ChatClassificationResult(
            conversation_id=row.conversation_id,
            branch_hash=row.branch_hash,
            primary_topic_key=fallback,
            secondary_topic_keys=(),
            request_type="other",
            confidence="low",
        )
        for row in empty
    ]
    if not nonempty:
        return ChatBatchResult(classifications=tuple(classifications), error_count=0)

    agent: Agent[_ChatClassificationDeps, _ChatAssignmentBatch] = Agent(
        get_pydantic_ai_model_name(model_name),
        deps_type=_ChatClassificationDeps,
        output_type=_ChatAssignmentBatch,
        system_prompt="Classify university-assistant chats consistently and conservatively.",
        retries=1,
    )
    agent.output_validator(_retry_invalid_chat_output)
    agent.instrument = False
    semaphore = asyncio.Semaphore(settings.CHAT_INSIGHTS_MAX_CONCURRENCY)
    batches = [
        nonempty[index : index + settings.CHAT_INSIGHTS_CHAT_BATCH_SIZE]
        for index in range(0, len(nonempty), settings.CHAT_INSIGHTS_CHAT_BATCH_SIZE)
    ]
    results = await asyncio.gather(
        *(
            _classify_chat_batch(agent, batch, definitions, semaphore, model_name)
            for batch in batches
        ),
        return_exceptions=True,
    )
    errors = 0
    for batch_number, (batch, batch_result) in enumerate(zip(batches, results, strict=True), 1):
        if isinstance(batch_result, BaseException):
            errors += 1
            _log_classification_batch_failure(
                batch_result,
                run_id=run_id,
                kind="chat",
                stage=stage,
                batch_number=batch_number,
                batch_count=len(batches),
                batch_size=len(batch),
            )
        else:
            classifications.extend(batch_result)
    return ChatBatchResult(classifications=tuple(classifications), error_count=errors)


def validate_document_assignment_payload(
    rows: list[DocumentClassificationInput],
    subjects: tuple[CategoryDefinition, ...],
    functions: tuple[CategoryDefinition, ...],
    payload: object,
) -> tuple[DocumentClassificationResult, ...]:
    output = _DocumentAssignmentBatch.model_validate(payload)
    allowed_subjects = {definition.key for definition in subjects}
    allowed_functions = {definition.key for definition in functions}
    returned = _assignments_by_item(output.assignments, len(rows))
    classifications: list[DocumentClassificationResult] = []
    for index, row in enumerate(rows, 1):
        assignment = returned[index]
        primary = _required_key(
            assignment.primary_subject, allowed_subjects, field="primary subject"
        )
        secondary = _validate_secondary_keys(
            assignment.secondary_subjects,
            allowed=allowed_subjects,
            primary=primary,
            field="secondary subject",
        )
        function = _required_key(
            assignment.document_function, allowed_functions, field="document function"
        )
        classifications.append(
            DocumentClassificationResult(
                source_key=row.source_key,
                content_hash=row.content_hash,
                primary_subject_key=primary,
                secondary_subject_keys=secondary,
                document_function_key=function,
                confidence=assignment.confidence,
                evidence_basis=row.evidence_basis,
            )
        )
    return tuple(classifications)


def _retry_invalid_document_output(
    ctx: RunContext[_DocumentClassificationDeps], output: _DocumentAssignmentBatch
) -> _DocumentAssignmentBatch:
    try:
        validate_document_assignment_payload(
            list(ctx.deps.rows), ctx.deps.subjects, ctx.deps.functions, output
        )
    except ClassificationOutputError as exc:
        raise ModelRetry(
            f"{exc}. Subject and function fields must use keys from their respective taxonomies."
        ) from exc
    return output


async def _classify_document_batch(
    agent: Agent[_DocumentClassificationDeps, _DocumentAssignmentBatch],
    rows: list[DocumentClassificationInput],
    subjects: tuple[CategoryDefinition, ...],
    functions: tuple[CategoryDefinition, ...],
    semaphore: asyncio.Semaphore,
    model_name: str,
) -> tuple[DocumentClassificationResult, ...]:
    async with semaphore:
        result = await agent.run(
            _document_prompt(rows, subjects, functions),
            deps=_DocumentClassificationDeps(
                rows=tuple(rows), subjects=subjects, functions=functions
            ),
            model_settings=_model_settings(model_name),
            usage_limits=UsageLimits(request_limit=2),
        )
    return validate_document_assignment_payload(rows, subjects, functions, result.output)


async def classify_documents(
    rows: list[DocumentClassificationInput],
    subjects: tuple[CategoryDefinition, ...],
    functions: tuple[CategoryDefinition, ...],
    *,
    model_name: str,
    run_id: UUID,
    stage: ClassificationStage,
) -> DocumentBatchResult:
    if not rows:
        return DocumentBatchResult(classifications=(), error_count=0)
    agent: Agent[_DocumentClassificationDeps, _DocumentAssignmentBatch] = Agent(
        get_pydantic_ai_model_name(model_name),
        deps_type=_DocumentClassificationDeps,
        output_type=_DocumentAssignmentBatch,
        system_prompt=(
            "Classify university knowledge documents consistently, separating subject from "
            "artifact function and using fallback categories rarely."
        ),
        retries=1,
    )
    agent.output_validator(_retry_invalid_document_output)
    agent.instrument = False
    semaphore = asyncio.Semaphore(settings.CHAT_INSIGHTS_MAX_CONCURRENCY)
    batches = [
        rows[index : index + settings.CHAT_INSIGHTS_DOCUMENT_BATCH_SIZE]
        for index in range(0, len(rows), settings.CHAT_INSIGHTS_DOCUMENT_BATCH_SIZE)
    ]
    results = await asyncio.gather(
        *(
            _classify_document_batch(agent, batch, subjects, functions, semaphore, model_name)
            for batch in batches
        ),
        return_exceptions=True,
    )
    classifications: list[DocumentClassificationResult] = []
    errors = 0
    for batch_number, (batch, batch_result) in enumerate(zip(batches, results, strict=True), 1):
        if isinstance(batch_result, BaseException):
            errors += 1
            _log_classification_batch_failure(
                batch_result,
                run_id=run_id,
                kind="document",
                stage=stage,
                batch_number=batch_number,
                batch_count=len(batches),
                batch_size=len(batch),
            )
        else:
            classifications.extend(batch_result)
    return DocumentBatchResult(classifications=tuple(classifications), error_count=errors)
