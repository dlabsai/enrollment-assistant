"""Copy runtime RAG tables into the guarded eval/test database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.storage import eval_report_session
from app.models import Document, DocumentContentChunk, GuardrailUrlRegistry, RagDocumentExclusion

_COPY_BATCH_SIZE = 250
_VECTOR_INDEX_DEFINITIONS: tuple[tuple[str, str], ...] = (
    (
        "idx_document_title_embedding",
        "CREATE INDEX idx_document_title_embedding ON document "
        "USING hnsw (title_embedding vector_l2_ops)",
    ),
    (
        "idx_document_content_chunk_content_embedding",
        "CREATE INDEX idx_document_content_chunk_content_embedding ON document_content_chunk "
        "USING hnsw (content_embedding vector_l2_ops)",
    ),
)

type EvalRagCopyStepStatus = Literal["pending", "running", "completed", "error"]

_COPY_STEPS: tuple[tuple[str, str], ...] = (
    ("prepare_eval_db", "Prepare Eval KB"),
    ("copy_documents", "Copy documents"),
    ("copy_chunks", "Copy chunks"),
    ("copy_guardrail_registries", "Copy guardrail registries"),
    ("copy_document_exclusions", "Copy document exclusions"),
    ("rebuild_vector_indexes", "Rebuild vector indexes"),
    ("commit", "Commit Eval KB sync"),
)


@dataclass(frozen=True)
class EvalRagCopyResult:
    documents: int
    chunks: int
    guardrail_registries: int
    document_exclusions: int


@dataclass(frozen=True)
class EvalRagCopyProgressStep:
    key: str
    label: str
    status: EvalRagCopyStepStatus


@dataclass(frozen=True)
class EvalRagCopyProgressSnapshot:
    steps: list[EvalRagCopyProgressStep]
    current_step: str | None
    finished_steps: int
    total_steps: int


type EvalRagCopyProgressCallback = Callable[[EvalRagCopyProgressSnapshot], Awaitable[None]]
type EvalRagCopyLogCallback = Callable[[str], Awaitable[None]]


def _build_progress_snapshot(
    step_statuses: dict[str, EvalRagCopyStepStatus], current_step: str | None
) -> EvalRagCopyProgressSnapshot:
    steps = [
        EvalRagCopyProgressStep(key=key, label=label, status=step_statuses[key])
        for key, label in _COPY_STEPS
    ]
    return EvalRagCopyProgressSnapshot(
        steps=steps,
        current_step=current_step,
        finished_steps=sum(1 for step in steps if step.status == "completed"),
        total_steps=len(steps),
    )


async def _emit_progress(
    progress_callback: EvalRagCopyProgressCallback | None,
    step_statuses: dict[str, EvalRagCopyStepStatus],
    current_step: str | None,
) -> None:
    if progress_callback is None:
        return
    await progress_callback(_build_progress_snapshot(step_statuses, current_step))


async def _emit_log(log_callback: EvalRagCopyLogCallback | None, message: str) -> None:
    if log_callback is None:
        return
    await log_callback(message)


async def _copy_model_rows[
    TModel: (Document, DocumentContentChunk, GuardrailUrlRegistry, RagDocumentExclusion)
](
    source_session: AsyncSession,
    destination_session: AsyncSession,
    model: type[TModel],
    *,
    batch_size: int = _COPY_BATCH_SIZE,
    column_overrides: dict[str, Any] | None = None,
    log_callback: EvalRagCopyLogCallback | None = None,
    row_label_singular: str,
    row_label_plural: str,
) -> int:
    columns = list(model.__table__.columns)
    total = (await source_session.execute(select(func.count(model.id)))).scalar_one()
    copied = 0
    batch: list[TModel] = []

    def row_label(count: int) -> str:
        return row_label_singular if count == 1 else row_label_plural

    await _emit_log(log_callback, f"Copying {total:,} {row_label(total)}...")

    async def flush_batch() -> None:
        nonlocal copied
        destination_session.add_all(batch)
        await destination_session.flush()
        copied += len(batch)
        batch.clear()
        await _emit_log(log_callback, f"Copied {copied:,}/{total:,} {row_label(total)}.")

    result = await source_session.stream_scalars(select(model).order_by(model.id))
    async for source_row in result:
        values = {column.name: getattr(source_row, column.name) for column in columns}
        if column_overrides is not None:
            values.update(column_overrides)
        batch.append(model(**values))
        if len(batch) >= batch_size:
            await flush_batch()

    if batch:
        await flush_batch()

    if total == 0:
        await _emit_log(log_callback, f"Copied 0/0 {row_label(total)}.")

    return copied


async def _drop_vector_indexes(session: AsyncSession) -> None:
    for index_name, _definition in _VECTOR_INDEX_DEFINITIONS:
        await session.execute(text(f"DROP INDEX IF EXISTS {index_name}"))


async def _create_vector_indexes(session: AsyncSession) -> None:
    for _index_name, definition in _VECTOR_INDEX_DEFINITIONS:
        await session.execute(text(definition))


async def copy_runtime_rag_to_eval_db(
    source_session: AsyncSession,
    *,
    progress_callback: EvalRagCopyProgressCallback | None = None,
    log_callback: EvalRagCopyLogCallback | None = None,
) -> EvalRagCopyResult:
    """Overwrite eval/test RAG tables with rows from the runtime DB.

    The eval DB safety checks live behind ``eval_report_session()``, which loads and migrates the
    guarded test/eval database. Embeddings are copied as-is, avoiding a fresh embedding rebuild.
    """
    step_statuses: dict[str, EvalRagCopyStepStatus] = {
        key: "pending" for key, _label in _COPY_STEPS
    }

    async def run_step[TResult](key: str, operation: Callable[[], Awaitable[TResult]]) -> TResult:
        step_statuses[key] = "running"
        await _emit_progress(progress_callback, step_statuses, key)
        try:
            result = await operation()
        except Exception:
            step_statuses[key] = "error"
            await _emit_progress(progress_callback, step_statuses, key)
            raise
        step_statuses[key] = "completed"
        await _emit_progress(progress_callback, step_statuses, None)
        return result

    async with eval_report_session() as destination_session:
        try:
            await run_step(
                "prepare_eval_db", lambda: _prepare_destination_eval_rag_db(destination_session)
            )

            documents = await run_step(
                "copy_documents",
                lambda: _copy_model_rows(
                    source_session,
                    destination_session,
                    Document,
                    log_callback=log_callback,
                    row_label_singular="document",
                    row_label_plural="documents",
                ),
            )
            chunks = await run_step(
                "copy_chunks",
                lambda: _copy_model_rows(
                    source_session,
                    destination_session,
                    DocumentContentChunk,
                    log_callback=log_callback,
                    row_label_singular="chunk",
                    row_label_plural="chunks",
                ),
            )
            guardrail_registries = await run_step(
                "copy_guardrail_registries",
                lambda: _copy_model_rows(
                    source_session,
                    destination_session,
                    GuardrailUrlRegistry,
                    log_callback=log_callback,
                    row_label_singular="guardrail registry",
                    row_label_plural="guardrail registries",
                ),
            )
            document_exclusions = await run_step(
                "copy_document_exclusions",
                lambda: _copy_model_rows(
                    source_session,
                    destination_session,
                    RagDocumentExclusion,
                    column_overrides={"created_by_user_id": None},
                    log_callback=log_callback,
                    row_label_singular="document exclusion",
                    row_label_plural="document exclusions",
                ),
            )
            await run_step(
                "rebuild_vector_indexes", lambda: _create_vector_indexes(destination_session)
            )
            await run_step("commit", destination_session.commit)
        except BaseException:
            await destination_session.rollback()
            raise

    return EvalRagCopyResult(
        documents=documents,
        chunks=chunks,
        guardrail_registries=guardrail_registries,
        document_exclusions=document_exclusions,
    )


async def _prepare_destination_eval_rag_db(destination_session: AsyncSession) -> None:
    await _drop_vector_indexes(destination_session)
    await destination_session.execute(
        text(
            "TRUNCATE rag_document_exclusion, guardrail_url_registry, "
            "document_content_chunk, document RESTART IDENTITY CASCADE"
        )
    )
    await destination_session.flush()
