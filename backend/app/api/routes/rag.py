import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast
from urllib.parse import unquote, urlparse
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    ColumnElement,
    String,
    asc,
    case,
    desc,
    func,
    literal,
    literal_column,
    or_,
    select,
)

from app.api.deps import CurrentUser, SessionDep, require_any_permission, require_permission
from app.api.schemas import PageOut
from app.chat.tools.utils import get_azure_openai_client
from app.core.rbac import PermissionKey
from app.evals.rag_copy import (
    EvalRagCopyProgressSnapshot,
    EvalRagCopyResult,
    copy_runtime_rag_to_eval_db,
)
from app.models import (
    Document,
    DocumentContentChunk,
    DocumentType,
    RagBuildJob,
    RagBuildJobDocumentChange,
    RagBuildJobSourceStat,
    RagBuildJobStep,
    RagDocumentExclusion,
    RagDocumentExclusionEvent,
    User,
)
from app.rag.build_notifications import (
    RagBuildNotificationPublisher,
    active_manual_rag_build_snapshot_events,
    listen_rag_build_notifications,
    publish_rag_build_notification,
)
from app.rag.constants import EMBEDDING_MODEL, EMBEDDING_VECTOR_DIMENSIONS
from app.rag.document_exclusions import RagExclusionFilter, apply_exclusion_filter
from app.rag.pipeline import (
    RagPipelineAlreadyRunningError,
    RagPipelineProgressSnapshot,
    run_rag_sync_pipeline,
)
from app.rag.training_materials.urls import (
    training_material_demo_url_from_url,
    training_material_path_from_url,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger(__name__)

RagAccessUser = Annotated[CurrentUser, Depends(require_permission(PermissionKey.ACCESS_RAG))]
RagBuildAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_RAG), scope="function")
]
RagViewerAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_RAG_VIEWER))
]
RagDocumentReadAccessUser = Annotated[
    CurrentUser,
    Depends(
        require_any_permission(PermissionKey.ACCESS_RAG_VIEWER, PermissionKey.ACCESS_RAG_EXCLUSIONS)
    ),
]
RagExclusionsAccessUser = Annotated[
    CurrentUser, Depends(require_permission(PermissionKey.ACCESS_RAG_EXCLUSIONS))
]

_WEBSITE_DOCUMENT_TYPES: tuple[DocumentType, ...] = (
    DocumentType.WEBSITE_PAGE,
    DocumentType.WEBSITE_PROGRAM,
)
_CATALOG_DOCUMENT_TYPES: tuple[DocumentType, ...] = (
    DocumentType.CATALOG_PAGE,
    DocumentType.CATALOG_PROGRAM,
    DocumentType.CATALOG_COURSE,
)
_TRAINING_MATERIAL_DOCUMENT_TYPES: tuple[DocumentType, ...] = (DocumentType.TRAINING_MATERIAL,)


class RagDocumentSummaryOut(BaseModel):
    id: UUID
    source_type: DocumentType
    source_id: int
    title: str
    url: str
    token_count: int
    character_count: int
    chunk_count: int
    source_key: str
    excluded: bool
    exclusion_reason: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None


class RagDocumentChunkOut(BaseModel):
    id: UUID
    sequence_number: int
    content: str
    token_count: int
    character_count: int
    created_at: datetime
    updated_at: datetime


class RagDocumentDetailOut(RagDocumentSummaryOut):
    markdown_content: str
    chunks: list[RagDocumentChunkOut]


class RagDocumentSimilarityMatchOut(RagDocumentSummaryOut):
    chunk_id: UUID
    sequence_number: int
    content: str
    chunk_token_count: int
    chunk_character_count: int
    distance: float


class RagDocumentChunkListItemOut(BaseModel):
    id: UUID
    sequence_number: int
    content: str
    token_count: int
    character_count: int
    created_at: datetime
    updated_at: datetime
    document: RagDocumentSummaryOut


class RagDocumentFileExtensionOut(BaseModel):
    extensions: list[str]


class RagDocumentExclusionSummaryOut(BaseModel):
    documents: int
    chunks: int
    tokens: int


class RagDocumentListOut(PageOut[RagDocumentSummaryOut]):
    excluded: RagDocumentExclusionSummaryOut


class RagDocumentExclusionIn(BaseModel):
    source_key: str = Field(min_length=1, max_length=2048)
    reason: str = Field(default="", max_length=255)


class RagDocumentExclusionOut(BaseModel):
    source_key: str
    reason: str
    created_at: datetime
    updated_at: datetime


RagDocumentExclusionEventAction = Literal["excluded", "included"]
RagDocumentExclusionEventFilter = Literal["all", "excluded", "included"]


class RagDocumentExclusionEventOut(BaseModel):
    id: UUID
    source_key: str
    action: RagDocumentExclusionEventAction
    reason: str | None
    document_title: str | None
    document_url: str | None
    source_type: DocumentType | None
    actor_name: str | None
    actor_email: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    document_id: UUID | None


class RagDocumentExclusionEventListOut(PageOut[RagDocumentExclusionEventOut]):
    pass


class RagDocumentTreeNodeOut(BaseModel):
    id: str
    label: str
    document_id: UUID | None = None
    source_type: DocumentType | None = None
    source_id: int | None = None
    excluded: bool = False
    children: list[RagDocumentTreeNodeOut] = Field(
        default_factory=lambda: cast("list[RagDocumentTreeNodeOut]", [])
    )


RagDocumentTreeNodeOut.model_rebuild()


@dataclass(frozen=True)
class _TreeDocument:
    id: UUID
    type: DocumentType
    id_: int
    title: str
    url: str
    excluded: bool


class RagBuildRequest(BaseModel):
    force_rebuild: bool = False
    resume_existing: bool = False


class RagBuildJobUserOut(BaseModel):
    id: UUID
    email: str
    name: str


class RagBuildJobSummaryOut(BaseModel):
    id: UUID
    job_name: str
    trigger: str
    status: str
    force_rebuild: bool
    started_by: RagBuildJobUserOut | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    current_step: str | None
    error_message: str | None
    total_new: int
    total_changed: int
    total_deleted: int
    total_unchanged: int
    total_source_documents: int
    total_existing_documents: int


class RagBuildJobStepOut(BaseModel):
    step_key: str
    label: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None


class RagBuildJobSourceStatOut(BaseModel):
    source_name: str
    document_type: str
    new_count: int
    changed_count: int
    deleted_count: int
    unchanged_count: int
    source_document_count: int
    existing_document_count: int


class RagBuildJobDocumentChangeOut(BaseModel):
    id: UUID
    source_name: str
    document_type: str
    change_type: str
    source_id: int
    source_key: str | None
    title: str
    url: str
    previous_title: str | None
    previous_url: str | None
    source_updated_at: datetime | None
    previous_source_updated_at: datetime | None


class RagBuildJobDetailOut(RagBuildJobSummaryOut):
    steps: list[RagBuildJobStepOut]
    source_stats: list[RagBuildJobSourceStatOut]
    document_changes: list[RagBuildJobDocumentChangeOut]


class RagBuildJobListOut(PageOut[RagBuildJobSummaryOut]):
    pass


class EvalRagCopyOut(BaseModel):
    documents: int
    chunks: int
    guardrail_registries: int
    document_exclusions: int


class EvalRagCopyResponse(BaseModel):
    copied: EvalRagCopyOut


type RagBuildJobSortBy = Literal[
    "started_at",
    "finished_at",
    "duration_ms",
    "status",
    "trigger",
    "new_count",
    "changed_count",
    "deleted_count",
]
type RagDocumentSortBy = Literal[
    "modified_at",
    "created_at",
    "title",
    "url",
    "source_type",
    "source_id",
    "source_key",
    "excluded",
    "token_count",
    "character_count",
    "chunk_count",
]
type RagDocumentChunkSortBy = Literal[
    "modified_at",
    "created_at",
    "title",
    "source_type",
    "source_id",
    "token_count",
    "character_count",
]
type RagDocumentExclusionEventSortBy = Literal[
    "created_at", "action", "document_title", "source_type", "actor"
]
type RagDocumentSearchMode = Literal["exact", "full_text"]


def _resolve_document_created_at(document: Document) -> datetime | None:
    return document.source_created_at or document.created_at


def _resolve_document_modified_at(document: Document) -> datetime | None:
    return document.source_updated_at or document.updated_at


def _viewer_document_types() -> tuple[DocumentType, ...]:
    return (*_WEBSITE_DOCUMENT_TYPES, *_CATALOG_DOCUMENT_TYPES, *_TRAINING_MATERIAL_DOCUMENT_TYPES)


def _viewer_source_type_conditions(
    source_types: list[DocumentType] | None,
) -> tuple[list[Any], bool]:
    viewer_document_types = _viewer_document_types()
    conditions: list[Any] = [Document.type.in_(viewer_document_types)]

    if source_types:
        allowed_source_types = [
            document_type
            for document_type in source_types
            if document_type in viewer_document_types
        ]
        if len(allowed_source_types) == 0:
            return conditions, False
        conditions.append(Document.type.in_(allowed_source_types))

    return conditions, True


def _knowledge_control_document_types() -> tuple[DocumentType, ...]:
    return (
        DocumentType.WEBSITE_PAGE,
        DocumentType.WEBSITE_PROGRAM,
        *_CATALOG_DOCUMENT_TYPES,
        *_TRAINING_MATERIAL_DOCUMENT_TYPES,
    )


def _exclusion_event_source_type_conditions(
    source_types: list[DocumentType] | None,
) -> tuple[list[Any], bool]:
    knowledge_control_source_type_values = tuple(
        document_type.value for document_type in _knowledge_control_document_types()
    )
    conditions: list[Any] = [
        or_(
            RagDocumentExclusionEvent.source_type.is_(None),
            RagDocumentExclusionEvent.source_type.in_(knowledge_control_source_type_values),
        )
    ]

    if source_types:
        allowed_source_type_values = tuple(
            document_type.value
            for document_type in source_types
            if document_type.value in knowledge_control_source_type_values
        )
        if len(allowed_source_type_values) == 0:
            return conditions, False
        conditions.append(RagDocumentExclusionEvent.source_type.in_(allowed_source_type_values))

    return conditions, True


def _normalize_document_file_extension(file_extension: str | None) -> str | None:
    if file_extension is None:
        return None

    normalized = file_extension.strip().casefold()
    while normalized.startswith("."):
        normalized = normalized[1:]

    if normalized == "":
        return None

    if not normalized.isalnum():
        raise HTTPException(
            status_code=400, detail="Document file extension must contain only letters and numbers"
        )

    return normalized


def _training_material_url_path_expr() -> Any:
    url_without_scheme = func.regexp_replace(Document.url, r"^training-materials://", "")
    return func.lower(func.split_part(url_without_scheme, "?", 1))


def _training_material_file_extension_condition(extension: str) -> Any:
    path = _training_material_url_path_expr()
    return (Document.type == DocumentType.TRAINING_MATERIAL) & path.op("~")(
        rf"(^|/)[^/]*\.{extension}$"
    )


def _append_document_file_extension_condition(
    conditions: list[Any], file_extension: str | None
) -> None:
    normalized = _normalize_document_file_extension(file_extension)
    if normalized is None:
        return

    if normalized == "html":
        conditions.append(Document.type != DocumentType.TRAINING_MATERIAL)
        return

    conditions.append(_training_material_file_extension_condition(normalized))


def _document_url_path_from_url(url: str) -> str:
    if url.startswith("training-materials://"):
        return training_material_path_from_url(url).strip("/")
    parsed_url = urlparse(url)
    return unquote(parsed_url.path).strip("/")


def _document_file_extension_from_document(
    document_type: DocumentType, title: str, url: str
) -> str | None:
    del title
    if document_type != DocumentType.TRAINING_MATERIAL:
        return "html"

    path = _document_url_path_from_url(url)
    filename = path.rsplit("/", 1)[-1] if path else ""
    _stem, separator, extension = filename.rpartition(".")
    normalized = extension.strip().casefold()
    if separator == "" or not normalized.isalnum():
        return None
    return normalized


def _to_eval_rag_copy_out(result: EvalRagCopyResult) -> EvalRagCopyOut:
    return EvalRagCopyOut(
        documents=result.documents,
        chunks=result.chunks,
        guardrail_registries=result.guardrail_registries,
        document_exclusions=result.document_exclusions,
    )


def _to_eval_rag_copy_progress_payload(snapshot: EvalRagCopyProgressSnapshot) -> dict[str, Any]:
    return {
        "steps": [
            {"key": step.key, "label": step.label, "status": step.status} for step in snapshot.steps
        ],
        "current_step": snapshot.current_step,
        "finished_steps": snapshot.finished_steps,
        "total_steps": snapshot.total_steps,
    }


def _format_count_label(count: int, *, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"


def _format_eval_rag_copy_result_message(result: EvalRagCopyResult) -> str:
    document_count = _format_count_label(result.documents, singular="document", plural="documents")
    chunk_count = _format_count_label(result.chunks, singular="chunk", plural="chunks")
    exclusion_count = _format_count_label(
        result.document_exclusions, singular="document exclusion", plural="document exclusions"
    )
    registry_count = _format_count_label(
        result.guardrail_registries, singular="guardrail registry", plural="guardrail registries"
    )
    return (
        f"Eval KB synced: {document_count}, {chunk_count}, "
        f"{exclusion_count}, and {registry_count} copied."
    )


def _to_rag_build_job_user(user: User | None) -> RagBuildJobUserOut | None:
    if user is None:
        return None
    return RagBuildJobUserOut(id=user.id, email=user.email, name=user.name)


def _to_rag_build_job_summary(
    job: RagBuildJob,
    user: User | None,
    *,
    total_new: int = 0,
    total_changed: int = 0,
    total_deleted: int = 0,
    total_unchanged: int = 0,
    total_source_documents: int = 0,
    total_existing_documents: int = 0,
) -> RagBuildJobSummaryOut:
    return RagBuildJobSummaryOut(
        id=job.id,
        job_name=job.job_name,
        trigger=job.trigger,
        status=job.status,
        force_rebuild=job.force_rebuild,
        started_by=_to_rag_build_job_user(user),
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
        current_step=job.current_step,
        error_message=job.error_message,
        total_new=total_new,
        total_changed=total_changed,
        total_deleted=total_deleted,
        total_unchanged=total_unchanged,
        total_source_documents=total_source_documents,
        total_existing_documents=total_existing_documents,
    )


def _rag_build_job_stats_subquery() -> Any:
    return (
        select(
            RagBuildJobSourceStat.job_id,
            func.coalesce(func.sum(RagBuildJobSourceStat.new_count), 0).label("total_new"),
            func.coalesce(func.sum(RagBuildJobSourceStat.changed_count), 0).label("total_changed"),
            func.coalesce(func.sum(RagBuildJobSourceStat.deleted_count), 0).label("total_deleted"),
            func.coalesce(func.sum(RagBuildJobSourceStat.unchanged_count), 0).label(
                "total_unchanged"
            ),
            func.coalesce(func.sum(RagBuildJobSourceStat.source_document_count), 0).label(
                "total_source_documents"
            ),
            func.coalesce(func.sum(RagBuildJobSourceStat.existing_document_count), 0).label(
                "total_existing_documents"
            ),
        )
        .group_by(RagBuildJobSourceStat.job_id)
        .subquery()
    )


def _document_display_url(document: Document) -> str:
    return (
        training_material_demo_url_from_url(document.url)
        if document.type == DocumentType.TRAINING_MATERIAL
        else document.url
    )


def _document_display_url_sort_expr() -> Any:
    training_path = func.regexp_replace(Document.url, r"^training-materials://", "")
    return case(
        (
            Document.type == DocumentType.TRAINING_MATERIAL,
            func.concat(
                literal("https://demo-university.example.edu/internal/training-materials/"),
                training_path,
            ),
        ),
        else_=Document.url,
    ).collate("C")


def _to_document_summary(
    document: Document, chunk_count: int, exclusion: RagDocumentExclusion | None = None
) -> RagDocumentSummaryOut:
    return RagDocumentSummaryOut(
        id=document.id,
        source_type=document.type,
        source_id=document.id_,
        title=document.title,
        url=_document_display_url(document),
        token_count=document.token_count,
        character_count=document.character_count,
        chunk_count=chunk_count,
        source_key=document.source_key,
        excluded=exclusion is not None,
        exclusion_reason=exclusion.reason if exclusion is not None else None,
        created_at=_resolve_document_created_at(document),
        modified_at=_resolve_document_modified_at(document),
    )


def _document_type_from_snapshot(value: str | None) -> DocumentType | None:
    if value is None:
        return None

    try:
        return DocumentType(value)
    except ValueError:
        return None


def _to_exclusion_event_out(
    event: RagDocumentExclusionEvent, document_id: UUID | None
) -> RagDocumentExclusionEventOut:
    return RagDocumentExclusionEventOut(
        id=event.id,
        source_key=event.source_key,
        action=cast("RagDocumentExclusionEventAction", event.action),
        reason=event.reason,
        document_title=event.document_title,
        document_url=event.document_url,
        source_type=_document_type_from_snapshot(event.source_type),
        actor_name=event.actor_name,
        actor_email=event.actor_email,
        created_by_user_id=event.created_by_user_id,
        created_at=event.created_at,
        document_id=document_id,
    )


def _build_exclusion_event(
    *,
    action: RagDocumentExclusionEventAction,
    current_user: User,
    document: Document | None,
    reason: str | None,
    source_key: str,
) -> RagDocumentExclusionEvent:
    return RagDocumentExclusionEvent(
        source_key=source_key,
        action=action,
        reason=reason,
        document_title=document.title if document is not None else None,
        document_url=_document_display_url(document) if document is not None else None,
        source_type=document.type.value if document is not None else None,
        actor_name=current_user.name,
        actor_email=current_user.email,
        created_by_user_id=current_user.id,
    )


def _document_type_label(document_type: DocumentType) -> str:
    match document_type:
        case DocumentType.WEBSITE_PAGE:
            return "Website pages"
        case DocumentType.WEBSITE_PROGRAM:
            return "Website programs"
        case DocumentType.CATALOG_PAGE:
            return "Catalog pages"
        case DocumentType.CATALOG_PROGRAM:
            return "Catalog programs"
        case DocumentType.CATALOG_COURSE:
            return "Catalog courses"
        case DocumentType.TRAINING_MATERIAL:
            return "Training materials"


def _document_tree_leaf(document: _TreeDocument) -> RagDocumentTreeNodeOut:
    return RagDocumentTreeNodeOut(
        id=f"document:{document.id}",
        label=document.title,
        document_id=document.id,
        source_type=document.type,
        source_id=document.id_,
        excluded=document.excluded,
    )


def _training_material_path_parts(document: _TreeDocument) -> list[str]:
    if not document.url.startswith("training-materials://"):
        return [document.title]

    relative_path = training_material_path_from_url(document.url).strip("/")
    path_parts = [part for part in relative_path.split("/") if part]
    return path_parts or [document.title]


def _get_or_create_tree_folder(
    children: list[RagDocumentTreeNodeOut], *, node_id: str, label: str
) -> RagDocumentTreeNodeOut:
    for child in children:
        if child.label == label and child.document_id is None:
            return child

    folder = RagDocumentTreeNodeOut(id=node_id, label=label)
    children.append(folder)
    return folder


def _insert_training_material_tree_document(
    root_children: list[RagDocumentTreeNodeOut], document: _TreeDocument
) -> None:
    path_parts = _training_material_path_parts(document)
    current_children = root_children

    for index, path_part in enumerate(path_parts):
        is_leaf = index == len(path_parts) - 1
        node_key = "/".join(path_parts[: index + 1])
        if is_leaf:
            current_children.append(
                RagDocumentTreeNodeOut(
                    id=f"document:{document.id}",
                    label=path_part,
                    document_id=document.id,
                    source_type=document.type,
                    source_id=document.id_,
                    excluded=document.excluded,
                )
            )
            return

        folder = _get_or_create_tree_folder(
            current_children, node_id=f"training-folder:{node_key}", label=path_part
        )
        current_children = folder.children


def _sort_document_tree_nodes(nodes: list[RagDocumentTreeNodeOut]) -> list[RagDocumentTreeNodeOut]:
    sorted_nodes = sorted(
        nodes, key=lambda node: (node.document_id is not None, node.label.casefold())
    )
    for node in sorted_nodes:
        node.children = _sort_document_tree_nodes(node.children)
    return sorted_nodes


def _format_sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _is_terminal_sse_event(event: str, payload: dict[str, Any]) -> bool:
    return event == "status" and payload.get("status") in {"complete", "error", "cancelled"}


def _notification_job_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("job_id")
    return value if isinstance(value, str) else None


def _payload_with_job_id(payload: dict[str, Any], job_id: str | None) -> dict[str, Any]:
    if job_id is None:
        return payload
    return {**payload, "job_id": job_id}


async def _next_rag_build_notification(
    notifications: AsyncIterator[tuple[str, dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    return await anext(notifications)


class _PipelineLogHandler(logging.Handler):
    def __init__(
        self, publisher: RagBuildNotificationPublisher, job_id_getter: Callable[[], UUID | None]
    ) -> None:
        super().__init__(level=logging.INFO)
        self._publisher = publisher
        self._job_id_getter = job_id_getter
        self.previous_level = logging.NOTSET

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return

        job_id = self._job_id_getter()
        if job_id is None:
            return

        stream = "stderr" if record.levelno >= logging.ERROR else "stdout"
        self._publisher.publish_nowait(
            "log", {"job_id": str(job_id), "stream": stream, "message": message}
        )


def _attach_pipeline_log_handler(handler: _PipelineLogHandler) -> None:
    app_logger = logging.getLogger("app")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.previous_level = app_logger.level
    if app_logger.getEffectiveLevel() > logging.INFO:
        app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)


def _detach_pipeline_log_handler(handler: _PipelineLogHandler) -> None:
    app_logger = logging.getLogger("app")
    app_logger.removeHandler(handler)
    app_logger.setLevel(handler.previous_level)


async def _run_manual_rag_build_notifications(
    *,
    force_rebuild: bool,
    started_by_user_id: UUID,
    started_job_id_future: asyncio.Future[UUID | None] | None = None,
) -> None:
    publisher = RagBuildNotificationPublisher()
    job_id: UUID | None = None

    def resolve_started_job_id(value: UUID | None) -> None:
        if started_job_id_future is not None and not started_job_id_future.done():
            started_job_id_future.set_result(value)

    def current_job_id() -> UUID | None:
        return job_id

    log_handler = _PipelineLogHandler(publisher, current_job_id)
    _attach_pipeline_log_handler(log_handler)

    async def publish_status(status: str, *, exit_code: int | None = None) -> None:
        payload: dict[str, Any] = {"status": status}
        if job_id is not None:
            payload["job_id"] = str(job_id)
        if exit_code is not None:
            payload["exit_code"] = exit_code
        await publish_rag_build_notification("status", payload)

    async def publish_error(message: str) -> None:
        payload: dict[str, Any] = {"message": message}
        if job_id is not None:
            payload["job_id"] = str(job_id)
        await publish_rag_build_notification("error", payload)

    async def on_job_started(started_job_id: UUID) -> None:
        nonlocal job_id
        job_id = started_job_id
        resolve_started_job_id(started_job_id)
        await publish_status("start")

    async def on_progress(snapshot: RagPipelineProgressSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        if job_id is not None:
            payload["job_id"] = str(job_id)
        await publish_rag_build_notification("progress", payload)

    terminal_status: tuple[str, int | None] | None = None
    terminal_error_message: str | None = None
    try:
        completed_job_id = await run_rag_sync_pipeline(
            job_name="api_rag_build",
            progress_callback=on_progress,
            force_rebuild=force_rebuild,
            job_trigger="manual",
            started_by_user_id=started_by_user_id,
            job_started_callback=on_job_started,
        )
        job_id = completed_job_id
        terminal_status = ("complete", 0)
    except asyncio.CancelledError:
        terminal_status = ("cancelled", None)
        raise
    except RagPipelineAlreadyRunningError as exc:
        terminal_error_message = str(exc)
        terminal_status = ("error", 409)
    except Exception as exc:
        logger.exception("Manual RAG build pipeline task failed")
        terminal_error_message = f"Failed to run RAG build: {exc}"
        terminal_status = ("error", 1)
    finally:
        resolve_started_job_id(job_id)
        _detach_pipeline_log_handler(log_handler)
        await publisher.close()
        if terminal_error_message is not None:
            await publish_error(terminal_error_message)
        if terminal_status is not None:
            status, exit_code = terminal_status
            await publish_status(status, exit_code=exit_code)


def _log_manual_rag_build_task_exception(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Manual RAG build notification task failed")


@router.get("/jobs", response_model=RagBuildJobListOut)
async def list_rag_build_jobs(
    session: SessionDep,
    _current_user: RagAccessUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query(max_length=32)] = None,
    trigger: Annotated[str | None, Query(max_length=32)] = None,
    sort_by: Annotated[RagBuildJobSortBy, Query()] = "started_at",
    descending: Annotated[bool, Query()] = True,
) -> RagBuildJobListOut:
    conditions: list[Any] = []
    if status is not None and status.strip() != "":
        conditions.append(RagBuildJob.status == status.strip())
    if trigger is not None and trigger.strip() != "":
        conditions.append(RagBuildJob.trigger == trigger.strip())

    total = (
        await session.execute(select(func.count(RagBuildJob.id)).where(*conditions))
    ).scalar_one()

    stats = _rag_build_job_stats_subquery()
    total_new_expr = func.coalesce(stats.c.total_new, 0)
    total_changed_expr = func.coalesce(stats.c.total_changed, 0)
    total_deleted_expr = func.coalesce(stats.c.total_deleted, 0)
    total_unchanged_expr = func.coalesce(stats.c.total_unchanged, 0)
    total_source_documents_expr = func.coalesce(stats.c.total_source_documents, 0)
    total_existing_documents_expr = func.coalesce(stats.c.total_existing_documents, 0)
    sort_expr_map: dict[RagBuildJobSortBy, Any] = {
        "started_at": RagBuildJob.started_at,
        "finished_at": RagBuildJob.finished_at,
        "duration_ms": RagBuildJob.duration_ms,
        "status": RagBuildJob.status,
        "trigger": RagBuildJob.trigger,
        "new_count": total_new_expr,
        "changed_count": total_changed_expr,
        "deleted_count": total_deleted_expr,
    }
    sort_expr = sort_expr_map[sort_by]
    order_by = desc(sort_expr).nullslast() if descending else asc(sort_expr).nullslast()

    rows = (
        await session.execute(
            select(
                RagBuildJob,
                User,
                total_new_expr.label("total_new"),
                total_changed_expr.label("total_changed"),
                total_deleted_expr.label("total_deleted"),
                total_unchanged_expr.label("total_unchanged"),
                total_source_documents_expr.label("total_source_documents"),
                total_existing_documents_expr.label("total_existing_documents"),
            )
            .outerjoin(User, User.id == RagBuildJob.started_by_user_id)
            .outerjoin(stats, stats.c.job_id == RagBuildJob.id)
            .where(*conditions)
            .order_by(order_by, RagBuildJob.started_at.desc(), RagBuildJob.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return RagBuildJobListOut(
        items=[
            _to_rag_build_job_summary(
                job,
                user,
                total_new=int(total_new),
                total_changed=int(total_changed),
                total_deleted=int(total_deleted),
                total_unchanged=int(total_unchanged),
                total_source_documents=int(total_source_documents),
                total_existing_documents=int(total_existing_documents),
            )
            for (
                job,
                user,
                total_new,
                total_changed,
                total_deleted,
                total_unchanged,
                total_source_documents,
                total_existing_documents,
            ) in rows
        ],
        total=total,
    )


@router.get("/jobs/{job_id}", response_model=RagBuildJobDetailOut)
async def get_rag_build_job(
    job_id: UUID, session: SessionDep, _current_user: RagAccessUser
) -> RagBuildJobDetailOut:
    stats = _rag_build_job_stats_subquery()
    total_new_expr = func.coalesce(stats.c.total_new, 0)
    total_changed_expr = func.coalesce(stats.c.total_changed, 0)
    total_deleted_expr = func.coalesce(stats.c.total_deleted, 0)
    total_unchanged_expr = func.coalesce(stats.c.total_unchanged, 0)
    total_source_documents_expr = func.coalesce(stats.c.total_source_documents, 0)
    total_existing_documents_expr = func.coalesce(stats.c.total_existing_documents, 0)

    row = (
        await session.execute(
            select(
                RagBuildJob,
                User,
                total_new_expr.label("total_new"),
                total_changed_expr.label("total_changed"),
                total_deleted_expr.label("total_deleted"),
                total_unchanged_expr.label("total_unchanged"),
                total_source_documents_expr.label("total_source_documents"),
                total_existing_documents_expr.label("total_existing_documents"),
            )
            .outerjoin(User, User.id == RagBuildJob.started_by_user_id)
            .outerjoin(stats, stats.c.job_id == RagBuildJob.id)
            .where(RagBuildJob.id == job_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="RAG build job not found")

    (
        job,
        user,
        total_new,
        total_changed,
        total_deleted,
        total_unchanged,
        total_source_documents,
        total_existing_documents,
    ) = row
    summary = _to_rag_build_job_summary(
        job,
        user,
        total_new=int(total_new),
        total_changed=int(total_changed),
        total_deleted=int(total_deleted),
        total_unchanged=int(total_unchanged),
        total_source_documents=int(total_source_documents),
        total_existing_documents=int(total_existing_documents),
    )

    steps = (
        await session.execute(
            select(RagBuildJobStep)
            .where(RagBuildJobStep.job_id == job.id)
            .order_by(RagBuildJobStep.created_at.asc(), RagBuildJobStep.step_key.asc())
        )
    ).scalars()
    source_stats = (
        await session.execute(
            select(RagBuildJobSourceStat)
            .where(RagBuildJobSourceStat.job_id == job.id)
            .order_by(
                RagBuildJobSourceStat.source_name.asc(), RagBuildJobSourceStat.document_type.asc()
            )
        )
    ).scalars()
    document_changes = (
        await session.execute(
            select(RagBuildJobDocumentChange)
            .where(RagBuildJobDocumentChange.job_id == job.id)
            .order_by(
                RagBuildJobDocumentChange.source_name.asc(),
                RagBuildJobDocumentChange.change_type.asc(),
                RagBuildJobDocumentChange.title.asc(),
                RagBuildJobDocumentChange.id.asc(),
            )
        )
    ).scalars()

    return RagBuildJobDetailOut(
        **summary.model_dump(),
        steps=[
            RagBuildJobStepOut(
                step_key=step.step_key,
                label=step.label,
                status=step.status,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in steps
        ],
        source_stats=[
            RagBuildJobSourceStatOut(
                source_name=source_stat.source_name,
                document_type=source_stat.document_type,
                new_count=source_stat.new_count,
                changed_count=source_stat.changed_count,
                deleted_count=source_stat.deleted_count,
                unchanged_count=source_stat.unchanged_count,
                source_document_count=source_stat.source_document_count,
                existing_document_count=source_stat.existing_document_count,
            )
            for source_stat in source_stats
        ],
        document_changes=[
            RagBuildJobDocumentChangeOut(
                id=change.id,
                source_name=change.source_name,
                document_type=change.document_type,
                change_type=change.change_type,
                source_id=change.source_id,
                source_key=change.source_key,
                title=change.title,
                url=change.url,
                previous_title=change.previous_title,
                previous_url=change.previous_url,
                source_updated_at=change.source_updated_at,
                previous_source_updated_at=change.previous_source_updated_at,
            )
            for change in document_changes
        ],
    )


@router.get("/documents", response_model=RagDocumentListOut)
async def list_rag_documents(
    session: SessionDep,
    _current_user: RagDocumentReadAccessUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query()] = None,
    search_mode: Annotated[RagDocumentSearchMode, Query()] = "exact",
    sort_by: Annotated[RagDocumentSortBy, Query()] = "modified_at",
    descending: Annotated[bool, Query()] = True,
    source_types: Annotated[list[DocumentType] | None, Query(alias="types")] = None,
    file_extension: Annotated[str | None, Query(max_length=32)] = None,
    exclusion: Annotated[RagExclusionFilter, Query()] = "all",
) -> RagDocumentListOut:
    conditions, has_allowed_source_types = _viewer_source_type_conditions(source_types)
    if not has_allowed_source_types:
        return RagDocumentListOut(
            excluded=RagDocumentExclusionSummaryOut(documents=0, chunks=0, tokens=0),
            items=[],
            total=0,
        )
    _append_document_file_extension_condition(conditions, file_extension)
    apply_exclusion_filter(conditions, exclusion)

    search_text = search.strip() if search is not None else ""
    search_vector: ColumnElement[Any] = literal_column("document.search_vector")
    full_text_query = None
    if search_text != "":
        if search_mode == "full_text":
            full_text_query = func.websearch_to_tsquery("simple", search_text)
            conditions.append(search_vector.op("@@")(full_text_query))
        else:
            search_query = f"%{search_text}%"
            conditions.append(
                or_(
                    Document.title.ilike(search_query),
                    Document.url.ilike(search_query),
                    Document.markdown_content.ilike(search_query),
                )
            )

    total = (await session.execute(select(func.count(Document.id)).where(*conditions))).scalar_one()

    chunk_counts = (
        select(
            DocumentContentChunk.document_id,
            func.count(DocumentContentChunk.id).label("chunk_count"),
        )
        .group_by(DocumentContentChunk.document_id)
        .subquery()
    )
    chunk_count_expr = func.coalesce(chunk_counts.c.chunk_count, 0)
    excluded_documents, excluded_chunks, excluded_tokens = (
        await session.execute(
            select(
                func.count(Document.id),
                func.coalesce(func.sum(chunk_count_expr), 0),
                func.coalesce(func.sum(Document.token_count), 0),
            )
            .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
            .join(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(*conditions)
        )
    ).one()

    created_at_expr = func.coalesce(Document.source_created_at, Document.created_at)
    modified_at_expr = func.coalesce(Document.source_updated_at, Document.updated_at)
    sort_expr_map: dict[RagDocumentSortBy, Any] = {
        "modified_at": modified_at_expr,
        "created_at": created_at_expr,
        "title": Document.title.collate("C"),
        "url": _document_display_url_sort_expr(),
        "source_type": Document.type.cast(String).collate("C"),
        "source_id": Document.id_,
        "source_key": Document.source_key.collate("C"),
        "excluded": RagDocumentExclusion.id.is_not(None),
        "token_count": Document.token_count,
        "character_count": Document.character_count,
        "chunk_count": chunk_count_expr,
    }

    sort_expr = sort_expr_map[sort_by]
    order_by = desc(sort_expr) if descending else asc(sort_expr)
    if full_text_query is not None:
        rank_expr = func.ts_rank_cd(search_vector, full_text_query)
        order_by_clauses = [desc(rank_expr), desc(modified_at_expr), desc(Document.id)]
    else:
        order_by_clauses = [order_by, desc(Document.id) if descending else asc(Document.id)]

    rows = (
        await session.execute(
            select(Document, chunk_count_expr.label("chunk_count"), RagDocumentExclusion)
            .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(*conditions)
            .order_by(*order_by_clauses)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return RagDocumentListOut(
        excluded=RagDocumentExclusionSummaryOut(
            documents=int(excluded_documents),
            chunks=int(excluded_chunks),
            tokens=int(excluded_tokens),
        ),
        items=[
            _to_document_summary(document, int(chunk_count), exclusion)
            for document, chunk_count, exclusion in rows
        ],
        total=total,
    )


@router.get("/documents/similarity", response_model=PageOut[RagDocumentSimilarityMatchOut])
async def search_rag_document_chunks_by_similarity(
    session: SessionDep,
    _current_user: RagViewerAccessUser,
    query: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    source_types: Annotated[list[DocumentType] | None, Query(alias="types")] = None,
    file_extension: Annotated[str | None, Query(max_length=32)] = None,
    exclusion: Annotated[RagExclusionFilter, Query()] = "all",
) -> PageOut[RagDocumentSimilarityMatchOut]:
    conditions, has_allowed_source_types = _viewer_source_type_conditions(source_types)
    if not has_allowed_source_types:
        return PageOut(items=[], total=0)
    _append_document_file_extension_condition(conditions, file_extension)
    apply_exclusion_filter(conditions, exclusion)

    openai = get_azure_openai_client()
    embedding_response = await openai.embeddings.create(
        input=query.strip(), model=EMBEDDING_MODEL, dimensions=EMBEDDING_VECTOR_DIMENSIONS
    )
    if len(embedding_response.data) != 1:
        raise HTTPException(status_code=502, detail="Embedding provider returned an invalid result")

    embedding = embedding_response.data[0].embedding
    distance_expr = DocumentContentChunk.content_embedding.l2_distance(embedding)

    chunk_counts = (
        select(
            DocumentContentChunk.document_id,
            func.count(DocumentContentChunk.id).label("chunk_count"),
        )
        .group_by(DocumentContentChunk.document_id)
        .subquery()
    )
    chunk_count_expr = func.coalesce(chunk_counts.c.chunk_count, 0)

    rows = (
        await session.execute(
            select(
                Document,
                DocumentContentChunk,
                chunk_count_expr.label("chunk_count"),
                distance_expr.label("distance"),
                RagDocumentExclusion,
            )
            .select_from(DocumentContentChunk)
            .join(Document, DocumentContentChunk.document_id == Document.id)
            .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(*conditions)
            .order_by(distance_expr.asc(), DocumentContentChunk.id.asc())
            .limit(limit)
        )
    ).all()

    return PageOut(
        items=[
            RagDocumentSimilarityMatchOut(
                **_to_document_summary(document, int(chunk_count), exclusion).model_dump(),
                chunk_id=chunk.id,
                sequence_number=chunk.sequence_number,
                content=chunk.content,
                chunk_token_count=chunk.token_count,
                chunk_character_count=chunk.character_count,
                distance=float(distance),
            )
            for document, chunk, chunk_count, distance, exclusion in rows
        ],
        total=len(rows),
    )


@router.get("/documents/chunks", response_model=PageOut[RagDocumentChunkListItemOut])
async def list_rag_document_chunks(
    session: SessionDep,
    _current_user: RagViewerAccessUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query()] = None,
    sort_by: Annotated[RagDocumentChunkSortBy, Query()] = "character_count",
    descending: Annotated[bool, Query()] = True,
    source_types: Annotated[list[DocumentType] | None, Query(alias="types")] = None,
    file_extension: Annotated[str | None, Query(max_length=32)] = None,
    exclusion: Annotated[RagExclusionFilter, Query()] = "all",
) -> PageOut[RagDocumentChunkListItemOut]:
    conditions, has_allowed_source_types = _viewer_source_type_conditions(source_types)
    if not has_allowed_source_types:
        return PageOut(items=[], total=0)
    _append_document_file_extension_condition(conditions, file_extension)
    apply_exclusion_filter(conditions, exclusion)

    search_text = search.strip() if search is not None else ""
    if search_text != "":
        conditions.append(DocumentContentChunk.content.ilike(f"%{search_text}%"))

    total = (
        await session.execute(
            select(func.count(DocumentContentChunk.id))
            .select_from(DocumentContentChunk)
            .join(Document, DocumentContentChunk.document_id == Document.id)
            .where(*conditions)
        )
    ).scalar_one()

    chunk_counts = (
        select(
            DocumentContentChunk.document_id,
            func.count(DocumentContentChunk.id).label("chunk_count"),
        )
        .group_by(DocumentContentChunk.document_id)
        .subquery()
    )
    chunk_count_expr = func.coalesce(chunk_counts.c.chunk_count, 0)
    sort_expr_map: dict[RagDocumentChunkSortBy, Any] = {
        "modified_at": DocumentContentChunk.updated_at,
        "created_at": DocumentContentChunk.created_at,
        "title": Document.title.collate("C"),
        "source_type": Document.type.cast(String).collate("C"),
        "source_id": Document.id_,
        "token_count": DocumentContentChunk.token_count,
        "character_count": DocumentContentChunk.character_count,
    }
    sort_expr = sort_expr_map[sort_by]
    order_by = desc(sort_expr) if descending else asc(sort_expr)

    rows = (
        await session.execute(
            select(
                DocumentContentChunk,
                Document,
                chunk_count_expr.label("chunk_count"),
                RagDocumentExclusion,
            )
            .select_from(DocumentContentChunk)
            .join(Document, DocumentContentChunk.document_id == Document.id)
            .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(*conditions)
            .order_by(
                order_by,
                desc(Document.id),
                DocumentContentChunk.sequence_number.asc(),
                DocumentContentChunk.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return PageOut(
        items=[
            RagDocumentChunkListItemOut(
                id=chunk.id,
                sequence_number=chunk.sequence_number,
                content=chunk.content,
                token_count=chunk.token_count,
                character_count=chunk.character_count,
                created_at=chunk.created_at,
                updated_at=chunk.updated_at,
                document=_to_document_summary(document, int(chunk_count), exclusion),
            )
            for chunk, document, chunk_count, exclusion in rows
        ],
        total=total,
    )


@router.get("/documents/tree", response_model=list[RagDocumentTreeNodeOut])
async def get_rag_documents_tree(
    session: SessionDep,
    _current_user: RagDocumentReadAccessUser,
    exclusion: Annotated[RagExclusionFilter, Query()] = "all",
) -> list[RagDocumentTreeNodeOut]:
    conditions: list[Any] = [Document.type.in_(_viewer_document_types())]
    apply_exclusion_filter(conditions, exclusion)
    rows = (
        await session.execute(
            select(
                Document.id,
                Document.type,
                Document.id_,
                Document.title,
                Document.url,
                RagDocumentExclusion.id.is_not(None).label("excluded"),
            )
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(*conditions)
            .order_by(Document.type.asc(), Document.title.collate("C").asc(), Document.id.asc())
        )
    ).all()
    documents = [
        _TreeDocument(id=id_, type=type_, id_=source_id, title=title, url=url, excluded=excluded)
        for id_, type_, source_id, title, url, excluded in rows
    ]

    website_root = RagDocumentTreeNodeOut(id="root:website", label="Website")
    catalog_root = RagDocumentTreeNodeOut(id="root:catalog", label="Catalog")
    training_root = RagDocumentTreeNodeOut(id="root:training", label="Training materials")

    type_nodes: dict[DocumentType, RagDocumentTreeNodeOut] = {}
    for document in documents:
        if document.type in _WEBSITE_DOCUMENT_TYPES:
            parent_root = website_root
        elif document.type in _CATALOG_DOCUMENT_TYPES:
            parent_root = catalog_root
        elif document.type == DocumentType.TRAINING_MATERIAL:
            _insert_training_material_tree_document(training_root.children, document)
            continue
        else:
            continue

        type_node = type_nodes.get(document.type)
        if type_node is None:
            type_node = RagDocumentTreeNodeOut(
                id=f"type:{document.type.value}", label=_document_type_label(document.type)
            )
            type_nodes[document.type] = type_node
            parent_root.children.append(type_node)

        type_node.children.append(_document_tree_leaf(document))

    for root in (website_root, catalog_root, training_root):
        root.children = _sort_document_tree_nodes(root.children)

    roots = [website_root, catalog_root, training_root]
    return [root for root in roots if root.children]


@router.get("/documents/file-extensions", response_model=RagDocumentFileExtensionOut)
async def get_rag_document_file_extensions(
    session: SessionDep, _current_user: RagViewerAccessUser
) -> RagDocumentFileExtensionOut:
    rows = (
        await session.execute(
            select(Document.type, Document.title, Document.url)
            .where(Document.type.in_(_viewer_document_types()))
            .order_by(Document.url.asc())
        )
    ).all()
    extensions = sorted(
        {
            extension
            for document_type, title, url in rows
            if (extension := _document_file_extension_from_document(document_type, title, url))
            is not None
        }
    )
    return RagDocumentFileExtensionOut(extensions=extensions)


@router.get("/documents/exclusion-events", response_model=RagDocumentExclusionEventListOut)
async def list_rag_document_exclusion_events(
    session: SessionDep,
    _current_user: RagExclusionsAccessUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query()] = None,
    action: Annotated[RagDocumentExclusionEventFilter, Query()] = "all",
    source_types: Annotated[list[DocumentType] | None, Query(alias="types")] = None,
    sort_by: Annotated[RagDocumentExclusionEventSortBy, Query()] = "created_at",
    descending: Annotated[bool, Query()] = True,
) -> RagDocumentExclusionEventListOut:
    conditions, has_allowed_source_types = _exclusion_event_source_type_conditions(source_types)
    if not has_allowed_source_types:
        return RagDocumentExclusionEventListOut(items=[], total=0)
    if action != "all":
        conditions.append(RagDocumentExclusionEvent.action == action)
    if search is not None and search.strip() != "":
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                RagDocumentExclusionEvent.document_title.ilike(pattern),
                RagDocumentExclusionEvent.document_url.ilike(pattern),
                RagDocumentExclusionEvent.source_key.ilike(pattern),
                RagDocumentExclusionEvent.actor_name.ilike(pattern),
                RagDocumentExclusionEvent.actor_email.ilike(pattern),
            )
        )

    total = await session.scalar(
        select(func.count()).select_from(RagDocumentExclusionEvent).where(*conditions)
    )
    actor_expr = func.coalesce(
        RagDocumentExclusionEvent.actor_name, RagDocumentExclusionEvent.actor_email, ""
    ).collate("C")
    sort_expr_map: dict[RagDocumentExclusionEventSortBy, Any] = {
        "action": RagDocumentExclusionEvent.action.collate("C"),
        "actor": actor_expr,
        "created_at": RagDocumentExclusionEvent.created_at,
        "document_title": func.coalesce(RagDocumentExclusionEvent.document_title, "").collate("C"),
        "source_type": func.coalesce(RagDocumentExclusionEvent.source_type, "").collate("C"),
    }
    sort_expr = sort_expr_map[sort_by]
    order_by = desc(sort_expr) if descending else asc(sort_expr)
    rows = (
        await session.execute(
            select(RagDocumentExclusionEvent, Document.id.label("document_id"))
            .outerjoin(Document, Document.source_key == RagDocumentExclusionEvent.source_key)
            .where(*conditions)
            .order_by(
                order_by,
                RagDocumentExclusionEvent.created_at.desc(),
                RagDocumentExclusionEvent.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return RagDocumentExclusionEventListOut(
        items=[_to_exclusion_event_out(event, document_id) for event, document_id in rows],
        total=total or 0,
    )


@router.put("/documents/exclusion", response_model=RagDocumentExclusionOut)
async def upsert_rag_document_exclusion(
    payload: RagDocumentExclusionIn, session: SessionDep, current_user: RagExclusionsAccessUser
) -> RagDocumentExclusionOut:
    source_key = payload.source_key.strip()
    reason = payload.reason.strip()
    document = await session.scalar(
        select(Document).where(Document.source_key == source_key).limit(1)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="RAG document not found")

    exclusion = await session.scalar(
        select(RagDocumentExclusion).where(RagDocumentExclusion.source_key == source_key)
    )
    if exclusion is None:
        exclusion = RagDocumentExclusion(
            source_key=source_key, reason=reason, created_by_user_id=current_user.id
        )
        session.add(exclusion)
        session.add(
            _build_exclusion_event(
                action="excluded",
                current_user=current_user,
                document=document,
                reason=reason,
                source_key=source_key,
            )
        )
    else:
        exclusion.reason = reason
    await session.commit()
    return RagDocumentExclusionOut(
        source_key=exclusion.source_key,
        reason=exclusion.reason,
        created_at=exclusion.created_at,
        updated_at=exclusion.updated_at,
    )


@router.delete("/documents/exclusion")
async def delete_rag_document_exclusion(
    source_key: Annotated[str, Query(min_length=1, max_length=2048)],
    session: SessionDep,
    current_user: RagExclusionsAccessUser,
) -> dict[str, bool]:
    normalized_source_key = source_key.strip()
    exclusion = await session.scalar(
        select(RagDocumentExclusion).where(RagDocumentExclusion.source_key == normalized_source_key)
    )
    if exclusion is not None:
        document = await session.scalar(
            select(Document).where(Document.source_key == normalized_source_key).limit(1)
        )
        session.add(
            _build_exclusion_event(
                action="included",
                current_user=current_user,
                document=document,
                reason=None,
                source_key=normalized_source_key,
            )
        )
        await session.delete(exclusion)
        await session.commit()
    return {"ok": True}


@router.get("/documents/{document_id}", response_model=RagDocumentDetailOut)
async def get_rag_document(
    document_id: UUID, session: SessionDep, _current_user: RagDocumentReadAccessUser
) -> RagDocumentDetailOut:
    row = (
        await session.execute(
            select(Document, RagDocumentExclusion)
            .outerjoin(RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key)
            .where(Document.id == document_id, Document.type.in_(_viewer_document_types()))
        )
    ).first()
    if row is None:
        document = None
        exclusion = None
    else:
        document, exclusion = row
    if document is None:
        raise HTTPException(status_code=404, detail="RAG document not found")

    chunks = list(
        (
            await session.execute(
                select(DocumentContentChunk)
                .where(DocumentContentChunk.document_id == document.id)
                .order_by(DocumentContentChunk.sequence_number.asc())
            )
        )
        .scalars()
        .all()
    )

    summary = _to_document_summary(document, len(chunks), exclusion)
    return RagDocumentDetailOut(
        **summary.model_dump(),
        markdown_content=document.markdown_content,
        chunks=[
            RagDocumentChunkOut(
                id=chunk.id,
                sequence_number=chunk.sequence_number,
                content=chunk.content,
                token_count=chunk.token_count,
                character_count=chunk.character_count,
                created_at=chunk.created_at,
                updated_at=chunk.updated_at,
            )
            for chunk in chunks
        ],
    )


@router.post("/eval-rag/copy", response_model=EvalRagCopyResponse)
async def copy_eval_rag_from_runtime(
    session: SessionDep, _current_user: RagBuildAccessUser
) -> EvalRagCopyResponse:
    result = await copy_runtime_rag_to_eval_db(session)
    return EvalRagCopyResponse(copied=_to_eval_rag_copy_out(result))


@router.post("/eval-rag/copy/stream", response_class=StreamingResponse)
async def stream_eval_rag_copy_from_runtime(
    session: SessionDep, _current_user: RagBuildAccessUser
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def publish(event: str, payload: dict[str, Any]) -> None:
            await queue.put((event, payload))

        async def on_progress(snapshot: EvalRagCopyProgressSnapshot) -> None:
            await publish("progress", _to_eval_rag_copy_progress_payload(snapshot))

        async def on_log(message: str) -> None:
            await publish("log", {"stream": "stdout", "message": message})

        async def run_copy() -> None:
            await publish("status", {"status": "start"})
            await publish(
                "log",
                {"stream": "stdout", "message": "Syncing Eval KB from the current KB index..."},
            )
            try:
                result = await copy_runtime_rag_to_eval_db(
                    session, progress_callback=on_progress, log_callback=on_log
                )
            except asyncio.CancelledError:
                await publish("status", {"status": "cancelled"})
                raise
            except Exception as exc:
                logger.exception("Eval KB sync failed")
                await publish("error", {"message": f"Failed to sync Eval KB: {exc}"})
                await publish("status", {"status": "error", "exit_code": 1})
                return

            await publish(
                "log", {"stream": "stdout", "message": _format_eval_rag_copy_result_message(result)}
            )
            await publish("status", {"status": "complete", "exit_code": 0})

        copy_task = asyncio.create_task(run_copy())
        try:
            while True:
                event, payload = await queue.get()
                yield _format_sse_event(event, payload)
                if _is_terminal_sse_event(event, payload):
                    break
        finally:
            if not copy_task.done():
                copy_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await copy_task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/build/stream", response_class=StreamingResponse)
async def stream_rag_build(
    http_request: Request,
    current_user: RagBuildAccessUser,
    build_request: Annotated[RagBuildRequest | None, Body()] = None,
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        observed_job_id: str | None = None
        build_task: asyncio.Task[None] | None = None

        async with listen_rag_build_notifications() as notifications:
            active_job_id, snapshot_events = await active_manual_rag_build_snapshot_events()
            if active_job_id is not None:
                observed_job_id = str(active_job_id)
                for event, payload in snapshot_events:
                    yield _format_sse_event(event, payload)
                    if _is_terminal_sse_event(event, payload):
                        return
            elif build_request is not None and build_request.resume_existing:
                return
            else:
                started_job_id_future: asyncio.Future[UUID | None] = (
                    asyncio.get_running_loop().create_future()
                )
                build_task = asyncio.create_task(
                    _run_manual_rag_build_notifications(
                        force_rebuild=build_request.force_rebuild
                        if build_request is not None
                        else False,
                        started_by_user_id=current_user.id,
                        started_job_id_future=started_job_id_future,
                    )
                )
                build_task.add_done_callback(_log_manual_rag_build_task_exception)
                started_job_id = await started_job_id_future
                if started_job_id is not None:
                    observed_job_id = str(started_job_id)

            notification_task = asyncio.create_task(_next_rag_build_notification(notifications))
            try:
                while True:
                    wait_tasks: set[asyncio.Task[Any]] = {notification_task}
                    if build_task is not None:
                        wait_tasks.add(build_task)

                    done, _pending = await asyncio.wait(
                        wait_tasks, return_when=asyncio.FIRST_COMPLETED
                    )

                    if build_task is not None and build_task in done:
                        try:
                            build_task.result()
                        except asyncio.CancelledError:
                            payload = _payload_with_job_id({"status": "cancelled"}, observed_job_id)
                            yield _format_sse_event("status", payload)
                            return
                        except Exception as exc:
                            error_payload = _payload_with_job_id(
                                {"message": f"RAG build stream failed: {exc}"}, observed_job_id
                            )
                            status_payload = _payload_with_job_id(
                                {"status": "error", "exit_code": 1}, observed_job_id
                            )
                            yield _format_sse_event("error", error_payload)
                            yield _format_sse_event("status", status_payload)
                            return
                        else:
                            build_task = None

                    if notification_task not in done:
                        continue

                    try:
                        event, payload = notification_task.result()
                    except StopAsyncIteration:
                        return
                    notification_task = asyncio.create_task(
                        _next_rag_build_notification(notifications)
                    )

                    if await http_request.is_disconnected():
                        return

                    notification_job_id = _notification_job_id(payload)
                    if observed_job_id is not None:
                        if notification_job_id != observed_job_id:
                            continue
                    elif notification_job_id is not None:
                        observed_job_id = notification_job_id

                    yield _format_sse_event(event, payload)
                    if _is_terminal_sse_event(event, payload):
                        return
            finally:
                notification_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await notification_task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
