import argparse
import asyncio
import html
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypedDict
from urllib.parse import parse_qs, urlparse

from openai import AsyncAzureOpenAI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import telemetry
from app.chat.models import (
    BaseRagModel,
    CatalogCourse,
    CatalogPage,
    CatalogProgram,
    TrainingMaterial,
    WebsitePage,
    WebsiteProgram,
    load_catalog_courses,
    load_catalog_pages,
    load_catalog_programs,
    load_training_materials,
    load_website_pages,
    load_website_programs,
)
from app.chat.tools.utils import get_azure_openai_client
from app.chat.url_guardrails import refresh_guardrail_url_registries
from app.core.db import get_session
from app.models import Document, DocumentContentChunk, DocumentType
from app.otel_genai import set_embedding_response_attributes
from app.rag.constants import EMBEDDING_MODEL, EMBEDDING_VECTOR_DIMENSIONS
from app.rag.demo_corpus.generate import write_demo_rag_data
from app.rag.source_keys import document_source_key
from app.rag.text_splitter import RecursiveCharacterTextSplitter
from app.tokens import count_tokens
from app.utils import configure_observability

# CHUNK_SIZE = 256
# CHUNK_OVERLAP = 32
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
EMBEDDING_BATCH_SIZE = 100
MAX_CONCURRENT_BATCHES = 5
_OUTLOOK_SAFE_LINK_HOST_SUFFIX = "safelinks.protection.outlook.com"
_OUTLOOK_SAFE_LINK_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'\]\)]*safelinks\.protection\.outlook\.com/[^\s<>\"'\]\)]*", re.IGNORECASE
)
_SAFE_LINK_TRAILING_PUNCTUATION = ".,;:"
_SAFE_LINK_MAX_UNWRAP_DEPTH = 5

configure_observability()


def _replace_website_domain(text: str) -> str:
    """Return source text unchanged for repo-local demo website documents."""
    return text


def _split_trailing_url_punctuation(url: str) -> tuple[str, str]:
    core = url
    trailing = ""
    while core and core[-1] in _SAFE_LINK_TRAILING_PUNCTUATION:
        trailing = f"{core[-1]}{trailing}"
        core = core[:-1]
    return core, trailing


def _is_outlook_safelink_url(url: str) -> bool:
    try:
        parsed = urlparse(html.unescape(url))
    except ValueError:
        return False
    return parsed.netloc.lower().endswith(_OUTLOOK_SAFE_LINK_HOST_SUFFIX)


def _outlook_safelink_target(url: str) -> str | None:
    try:
        query = urlparse(html.unescape(url)).query
    except ValueError:
        return None
    target = parse_qs(query, keep_blank_values=True).get("url", [None])[0]
    return target.strip() if target else None


def _unwrap_outlook_safelink_url(url: str) -> str | None:
    current = html.unescape(url).strip()
    for _ in range(_SAFE_LINK_MAX_UNWRAP_DEPTH):
        if not _is_outlook_safelink_url(current):
            return current
        target = _outlook_safelink_target(current)
        if target is None:
            return None
        current = html.unescape(target).strip()
    return None if _is_outlook_safelink_url(current) else current


def _safelink_replacement(match: re.Match[str]) -> str:
    matched_url = match.group(0)
    core_url, trailing = _split_trailing_url_punctuation(matched_url)
    target_url = _unwrap_outlook_safelink_url(core_url)
    return f"{target_url}{trailing}" if target_url is not None else matched_url


def _sanitize_rag_markdown_content(markdown_content: str) -> str:
    """Normalize source Markdown before storage, chunking, and embedding."""
    return _OUTLOOK_SAFE_LINK_URL_PATTERN.sub(_safelink_replacement, markdown_content)


def _source_fields_from_model(model: BaseRagModel) -> tuple[str, str, str]:
    is_website = isinstance(model, (WebsitePage, WebsiteProgram))
    title = _replace_website_domain(model.title) if is_website else model.title
    url = _replace_website_domain(model.url) if is_website else model.url
    markdown_content = (
        _replace_website_domain(model.markdown_content) if is_website else model.markdown_content
    )
    markdown_content = _sanitize_rag_markdown_content(markdown_content)
    if is_website:
        markdown_content = _replace_website_domain(markdown_content)
    return title, url, markdown_content


@dataclass
class DocumentCategories:
    """Categorization of documents based on comparison with existing database."""

    new: list[BaseRagModel]  # Documents that don't exist in DB
    changed: list[tuple[BaseRagModel, Document]]  # Updated documents (source, db)
    unchanged: list[tuple[BaseRagModel, Document]]  # Documents that haven't changed (source, db)
    deleted: list[Document]  # Documents in DB but not in source


RagBuildDocumentChangeType = Literal["new", "changed", "deleted"]


@dataclass(frozen=True)
class RagBuildDocumentChange:
    """A document-level source change observed during a RAG build."""

    change_type: RagBuildDocumentChangeType
    source_id: int
    source_key: str | None
    title: str
    url: str
    previous_title: str | None = None
    previous_url: str | None = None
    source_updated_at: datetime | None = None
    previous_source_updated_at: datetime | None = None


@dataclass(frozen=True)
class RagBuildSourceStats:
    """Per-source RAG build change counts and changed document identities."""

    source_name: str
    document_type: DocumentType
    new_count: int
    changed_count: int
    deleted_count: int
    unchanged_count: int
    source_document_count: int
    existing_document_count: int
    document_changes: list[RagBuildDocumentChange]


@dataclass(frozen=True)
class _DocumentSnapshot:
    source_id: int
    source_key: str
    document_type: DocumentType
    title: str
    url: str
    markdown_content: str
    source_updated_at: datetime | None


type RagBuildStatsCallback = Callable[[RagBuildSourceStats], Awaitable[None]]


def _create_batches[T](items: list[T], batch_size: int) -> list[list[T]]:
    """Split items into batches of specified size."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


async def _create_embeddings_batch(
    sem: asyncio.Semaphore, openai: AsyncAzureOpenAI, texts: list[str]
) -> list[list[float]]:
    """Create embeddings for a batch of texts in a single API call."""
    async with sem:
        with telemetry.span("rag.create_embeddings_batch") as span:
            span.set_attribute("gen_ai.operation.name", "embeddings")
            span.set_attribute("gen_ai.provider.name", "azure.ai.openai")
            span.set_attribute("gen_ai.request.model", EMBEDDING_MODEL)
            span.set_attribute("app.rag.batch_size", len(texts))
            span.set_attribute("app.rag.embedding_dimensions", EMBEDDING_VECTOR_DIMENSIONS)
            embedding_response = await openai.embeddings.create(
                input=texts,  # List of texts instead of single text
                model=EMBEDDING_MODEL,
                dimensions=EMBEDDING_VECTOR_DIMENSIONS,
            )
            set_embedding_response_attributes(span, embedding_response, model=EMBEDDING_MODEL)
            return [embedding.embedding for embedding in embedding_response.data]


async def _create_embeddings_batch_with_index(
    sem: asyncio.Semaphore, openai: AsyncAzureOpenAI, batch_index: int, texts: list[str]
) -> tuple[int, list[list[float]]]:
    return batch_index, await _create_embeddings_batch(sem, openai, texts)


def _get_document_type(model: BaseRagModel) -> DocumentType:
    if isinstance(model, CatalogPage):
        return DocumentType.CATALOG_PAGE
    if isinstance(model, CatalogProgram):
        return DocumentType.CATALOG_PROGRAM
    if isinstance(model, CatalogCourse):
        return DocumentType.CATALOG_COURSE
    if isinstance(model, WebsitePage):
        return DocumentType.WEBSITE_PAGE
    if isinstance(model, WebsiteProgram):
        return DocumentType.WEBSITE_PROGRAM
    if isinstance(model, TrainingMaterial):
        return DocumentType.TRAINING_MATERIAL
    raise ValueError(f"Unknown model type: {type(model)}")


class DocumentData(TypedDict):
    type: DocumentType
    id_: int
    source_key: str
    title: str
    url: str
    markdown_content: str
    token_count: int
    character_count: int
    title_text: str
    title_embedding: list[float] | None
    school: str | None
    source_created_at: datetime | None
    source_updated_at: datetime | None


type ChunkData = tuple[int, str, int, int]
type ChunkDataWithEmbedding = tuple[int, str, int, int, list[float]]
type DocumentDataWithChunks = tuple[DocumentData, list[ChunkData]]
type DocumentDataWithChunksAndEmbeddings = tuple[DocumentData, list[ChunkDataWithEmbedding]]
type DocumentSource = tuple[Callable[[], Sequence[BaseRagModel]], str, DocumentType]


_MISSING_TABLE_CELL_VALUES = frozenset({"", "nan", "nat"})


def _is_markdown_table_row(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_missing_only_markdown_table_chunk(text: str) -> bool:
    """Return True when every nonblank line is a missing-value Markdown table row."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or any(not _is_markdown_table_row(line) for line in lines):
        return False

    data_row_count = 0
    for row in lines:
        cells = [cell.strip().lower() for cell in row.strip("|").split("|")]
        if cells and all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        data_row_count += 1
        if any(cell not in _MISSING_TABLE_CELL_VALUES for cell in cells):
            return False

    return data_row_count > 0


def _is_indexable_chunk(text: str) -> bool:
    """Return True when a split chunk has useful content for embedding."""
    return any(char.isalnum() for char in text) and not _is_missing_only_markdown_table_chunk(text)


def _get_document_sources() -> list[DocumentSource]:
    return [
        (load_catalog_pages, "catalog pages", DocumentType.CATALOG_PAGE),
        (load_catalog_courses, "catalog courses", DocumentType.CATALOG_COURSE),
        (load_catalog_programs, "catalog programs", DocumentType.CATALOG_PROGRAM),
        (load_website_pages, "website pages", DocumentType.WEBSITE_PAGE),
        (load_website_programs, "website programs", DocumentType.WEBSITE_PROGRAM),
        (load_training_materials, "training materials", DocumentType.TRAINING_MATERIAL),
    ]


def _normalize_datetime(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC timezone-aware, or None.

    Handles comparison between naive and timezone-aware datetimes by
    treating naive datetimes as UTC. This ensures consistent comparisons
    between source documents (which may have naive timestamps) and database
    records (which are always timezone-aware).

    Args:
        dt: A datetime that may be naive or timezone-aware, or None

    Returns:
        A timezone-aware datetime in UTC, or None if input was None

    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=UTC)
    return dt


async def _prepare_document_data[T: BaseRagModel](
    models: Sequence[T],
    text_splitter: RecursiveCharacterTextSplitter,
    model_type_name: str,
    source_id_overrides: Mapping[str, int] | None = None,
) -> list[DocumentDataWithChunks]:
    """Prepare document data without creating SQLAlchemy models or embeddings.

    Returns a list of tuples (document_data, chunk_data_list).
    """
    document_data_list: list[DocumentDataWithChunks] = []

    for model in models:
        # Extract school if it's a CatalogProgram
        school = None
        if isinstance(model, CatalogProgram):
            school = model.school

        # Apply source-independent Markdown normalization before hashing, chunking, and storage.
        title, url, markdown_content = _source_fields_from_model(model)

        # Prepare document data
        # Normalize timestamps to ensure timezone-aware storage in UTC
        document_type = _get_document_type(model)
        source_id = int(model.id)
        source_key = document_source_key(document_type, source_id, title, url, markdown_content)
        document_id = (
            source_id_overrides.get(source_key, source_id)
            if source_id_overrides is not None
            else source_id
        )
        doc_data: DocumentData = {
            "type": document_type,
            "id_": document_id,
            "source_key": source_key,
            "title": title,
            "url": url,
            "markdown_content": markdown_content,
            "token_count": count_tokens(markdown_content),
            "character_count": len(markdown_content),
            "title_text": title,  # For embedding later
            "title_embedding": None,  # Will be filled later
            "school": school,
            "source_created_at": _normalize_datetime(model.created),
            "source_updated_at": _normalize_datetime(model.updated),
        }

        # Split content into chunks
        text_chunks = text_splitter.split_text(markdown_content)

        # Prepare chunk data, filtering out chunks without useful indexed content.
        chunk_data: list[ChunkData] = [
            (i, text_chunk, count_tokens(text_chunk), len(text_chunk))
            for i, text_chunk in enumerate(text_chunks)
            if _is_indexable_chunk(text_chunk)
        ]

        document_data_list.append((doc_data, chunk_data))

    telemetry.info(
        "Prepared {count} {type} documents with {chunk_count} total chunks",
        count=len(document_data_list),
        type=model_type_name,
        chunk_count=sum(len(chunks) for _, chunks in document_data_list),
    )

    return document_data_list


async def _create_embeddings_for_documents(
    openai: AsyncAzureOpenAI, document_data_list: list[DocumentDataWithChunks]
) -> list[DocumentDataWithChunksAndEmbeddings]:
    """Create embeddings using batching for improved performance."""
    # Create semaphore for batch-level concurrency
    sem = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

    # Step 1: Collect all texts that need embeddings
    title_texts: list[str] = []
    chunk_texts: list[str] = []
    title_indices: list[int] = []  # Track which document each title belongs to
    chunk_indices: list[
        tuple[int, int]
    ] = []  # Track which (doc_idx, chunk_idx) each chunk belongs to

    for doc_idx, (doc_data, chunk_data) in enumerate(document_data_list):
        # Collect title text
        title_texts.append(doc_data["title_text"])
        title_indices.append(doc_idx)

        # Collect chunk texts
        for chunk_idx, (_, content, _token_count, _character_count) in enumerate(chunk_data):
            chunk_texts.append(content)
            chunk_indices.append((doc_idx, chunk_idx))

    # Step 2: Create batches
    title_batches = _create_batches(title_texts, EMBEDDING_BATCH_SIZE)
    chunk_batches = _create_batches(chunk_texts, EMBEDDING_BATCH_SIZE)

    # Step 3: Process title batches concurrently
    telemetry.info(
        "Creating embeddings for {count} titles in {batches} batches",
        count=len(title_texts),
        batches=len(title_batches),
    )

    title_batch_results: list[list[list[float]] | None] = [None] * len(title_batches)
    title_batch_tasks = [
        _create_embeddings_batch_with_index(sem, openai, batch_index, batch)
        for batch_index, batch in enumerate(title_batches)
    ]
    for completed_title_batches, title_task in enumerate(
        asyncio.as_completed(title_batch_tasks), start=1
    ):
        batch_index, batch_result = await title_task
        title_batch_results[batch_index] = batch_result
        telemetry.info(
            "Embedding title batch progress: {done}/{total} batches",
            done=completed_title_batches,
            total=len(title_batches),
        )

    # Step 4: Process chunk batches concurrently
    telemetry.info(
        "Creating embeddings for {count} chunks in {batches} batches",
        count=len(chunk_texts),
        batches=len(chunk_batches),
    )

    chunk_batch_results: list[list[list[float]] | None] = [None] * len(chunk_batches)
    chunk_batch_tasks = [
        _create_embeddings_batch_with_index(sem, openai, batch_index, batch)
        for batch_index, batch in enumerate(chunk_batches)
    ]
    for completed_chunk_batches, chunk_task in enumerate(
        asyncio.as_completed(chunk_batch_tasks), start=1
    ):
        batch_index, batch_result = await chunk_task
        chunk_batch_results[batch_index] = batch_result
        telemetry.info(
            "Embedding chunk batch progress: {done}/{total} batches",
            done=completed_chunk_batches,
            total=len(chunk_batches),
        )

    # Step 5: Flatten and map results back to documents
    # Flatten title results
    title_embeddings: list[list[float]] = []
    for batch_result in title_batch_results:
        assert batch_result is not None
        title_embeddings.extend(batch_result)

    # Flatten chunk results
    chunk_embeddings: list[list[float]] = []
    for batch_result in chunk_batch_results:
        assert batch_result is not None
        chunk_embeddings.extend(batch_result)

    # Step 6: Map embeddings back to documents
    # Update document data with title embeddings
    for i, embedding in enumerate(title_embeddings):
        doc_idx = title_indices[i]
        document_data_list[doc_idx][0]["title_embedding"] = embedding

    # Create result with chunk embeddings
    result: list[DocumentDataWithChunksAndEmbeddings] = []
    chunk_embedding_idx = 0

    for _doc_idx, (doc_data, chunk_data) in enumerate(document_data_list):
        doc_chunks_with_embeddings: list[ChunkDataWithEmbedding] = []

        for _chunk_idx, (seq_num, content, token_count, character_count) in enumerate(chunk_data):
            embedding = chunk_embeddings[chunk_embedding_idx]
            doc_chunks_with_embeddings.append(
                (seq_num, content, token_count, character_count, embedding)
            )
            chunk_embedding_idx += 1

        result.append((doc_data, doc_chunks_with_embeddings))

    return result


async def _insert_documents_to_db(
    session: AsyncSession,
    document_data_list: list[DocumentDataWithChunksAndEmbeddings],
    model_type_name: str,
) -> None:
    """Insert all documents and chunks into the database."""
    document_count = 0
    chunk_count = 0

    # Insert all documents and chunks
    for doc_data, chunk_data in document_data_list:
        # Create and add document
        document = Document(
            type=doc_data["type"],
            id_=doc_data["id_"],
            source_key=doc_data["source_key"],
            title=doc_data["title"],
            url=doc_data["url"],
            markdown_content=doc_data["markdown_content"],
            token_count=doc_data["token_count"],
            character_count=doc_data["character_count"],
            title_embedding=doc_data["title_embedding"],
            school=doc_data["school"],
            source_created_at=doc_data["source_created_at"],
            source_updated_at=doc_data["source_updated_at"],
        )
        session.add(document)
        await session.flush()  # Flush to get the document ID

        # Create and add chunks
        for seq_num, content, token_count, character_count, embedding in chunk_data:
            chunk = DocumentContentChunk(
                sequence_number=seq_num,
                content=content,
                token_count=token_count,
                character_count=character_count,
                content_embedding=embedding,
                document_id=document.id,
            )
            session.add(chunk)

        document_count += 1
        chunk_count += len(chunk_data)

    telemetry.info(
        "Inserted {count} {type} documents with {chunk_count} chunks into database",
        count=document_count,
        type=model_type_name,
        chunk_count=chunk_count,
    )


async def _process_documents[T: BaseRagModel](
    openai: AsyncAzureOpenAI,
    session: AsyncSession,
    models: Sequence[T],
    text_splitter: RecursiveCharacterTextSplitter,
    model_type_name: str,
    source_id_overrides: Mapping[str, int] | None = None,
) -> None:
    """Process a list of documents with batched embedding creation."""
    # Step 1: Prepare document data without creating SQLAlchemy models
    document_data_list = await _prepare_document_data(
        models, text_splitter, model_type_name, source_id_overrides=source_id_overrides
    )

    # Step 2: Create embeddings using batching for improved performance
    document_data_with_embeddings = await _create_embeddings_for_documents(
        openai, document_data_list
    )

    # Step 3: Insert all documents and chunks into the database
    await _insert_documents_to_db(session, document_data_with_embeddings, model_type_name)


async def _load_existing_documents(
    session: AsyncSession, doc_type: DocumentType
) -> dict[int, Document]:
    """Load all existing documents of a given type from the database.

    Returns a dictionary keyed by document id_ for quick lookup.
    """
    result = await session.execute(select(Document).where(Document.type == doc_type))
    documents = result.scalars().all()
    return {doc.id_: doc for doc in documents}


def _categorize_documents(
    source_docs: Sequence[BaseRagModel], db_docs: dict[int, Document]
) -> DocumentCategories:
    """Categorize documents by comparing source data with existing database.

    Documents are categorized as:
    - NEW: Present in source but not in database
    - CHANGED: Present in both, but the source update marker differs
    - UNCHANGED: Present in both with a matching source update marker
    - DELETED: Present in database but not in source

    Normal website and catalog sources have reliable upstream timestamps, so their
    source_updated_at timestamps are the primary update marker. The normalized rendered
    payload is also compared so source-normalization changes such as SafeLinks unwrapping
    reprocess affected documents even when upstream timestamps are unchanged. Synthetic
    PDFs, standalone synthetic calendars, and training materials do not have reliable
    upstream content timestamps; for those sources, ignore timestamp-only churn and compare
    the rendered payload against the committed DB row.
    """
    new_docs: list[BaseRagModel] = []
    changed_docs: list[tuple[BaseRagModel, Document]] = []
    unchanged_docs: list[tuple[BaseRagModel, Document]] = []

    db_docs_by_source_key = {doc.source_key: doc for doc in db_docs.values()}
    matched_db_source_keys: set[str] = set()

    # Categorize source documents
    for source_doc in source_docs:
        doc_id = int(source_doc.id)
        source_snapshot = _document_snapshot_from_source(source_doc)
        db_doc = db_docs_by_source_key.get(source_snapshot.source_key) or db_docs.get(doc_id)

        if db_doc is None:
            # Document doesn't exist in DB
            new_docs.append(source_doc)
        else:
            matched_db_source_keys.add(db_doc.source_key)
            if _is_document_changed(source_snapshot, db_doc):
                # Document has been updated
                changed_docs.append((source_doc, db_doc))
            else:
                # Document unchanged
                unchanged_docs.append((source_doc, db_doc))

    # Find deleted documents (in DB but not in source)
    deleted_docs = [
        db_doc for db_doc in db_docs.values() if db_doc.source_key not in matched_db_source_keys
    ]

    return DocumentCategories(
        new=new_docs, changed=changed_docs, unchanged=unchanged_docs, deleted=deleted_docs
    )


def _is_document_changed(snapshot: _DocumentSnapshot, db_doc: Document) -> bool:
    if snapshot.document_type == DocumentType.TRAINING_MATERIAL:
        return (
            snapshot.source_key != db_doc.source_key
            or snapshot.title != db_doc.title
            or snapshot.url != db_doc.url
            or snapshot.markdown_content != db_doc.markdown_content
        )

    if (
        snapshot.source_key != db_doc.source_key
        or snapshot.title != db_doc.title
        or snapshot.url != db_doc.url
        or snapshot.markdown_content != db_doc.markdown_content
    ):
        return True

    # Normalize both timestamps to ensure consistent comparison
    # (handles timezone-aware vs naive datetime comparison)
    source_updated = snapshot.source_updated_at
    db_updated = _normalize_datetime(db_doc.source_updated_at)
    return source_updated != db_updated


def _document_snapshot_from_source(model: BaseRagModel) -> _DocumentSnapshot:
    title, url, markdown_content = _source_fields_from_model(model)
    document_type = _get_document_type(model)
    source_id = int(model.id)
    return _DocumentSnapshot(
        source_id=source_id,
        source_key=document_source_key(document_type, source_id, title, url, markdown_content),
        document_type=document_type,
        title=title,
        url=url,
        markdown_content=markdown_content,
        source_updated_at=_normalize_datetime(model.updated),
    )


def _build_source_stats(
    categories: DocumentCategories, model_type_name: str, doc_type: DocumentType
) -> RagBuildSourceStats:
    document_changes: list[RagBuildDocumentChange] = []

    for source_doc in categories.new:
        snapshot = _document_snapshot_from_source(source_doc)
        document_changes.append(
            RagBuildDocumentChange(
                change_type="new",
                source_id=snapshot.source_id,
                source_key=snapshot.source_key,
                title=snapshot.title,
                url=snapshot.url,
                source_updated_at=snapshot.source_updated_at,
            )
        )

    for source_doc, db_doc in categories.changed:
        snapshot = _document_snapshot_from_source(source_doc)
        document_changes.append(
            RagBuildDocumentChange(
                change_type="changed",
                source_id=db_doc.id_,
                source_key=snapshot.source_key,
                title=snapshot.title,
                url=snapshot.url,
                previous_title=db_doc.title,
                previous_url=db_doc.url,
                source_updated_at=snapshot.source_updated_at,
                previous_source_updated_at=_normalize_datetime(db_doc.source_updated_at),
            )
        )

    for db_doc in categories.deleted:
        document_changes.append(
            RagBuildDocumentChange(
                change_type="deleted",
                source_id=db_doc.id_,
                source_key=db_doc.source_key,
                title=db_doc.title,
                url=db_doc.url,
                previous_title=db_doc.title,
                previous_url=db_doc.url,
                previous_source_updated_at=_normalize_datetime(db_doc.source_updated_at),
            )
        )

    return RagBuildSourceStats(
        source_name=model_type_name,
        document_type=doc_type,
        new_count=len(categories.new),
        changed_count=len(categories.changed),
        deleted_count=len(categories.deleted),
        unchanged_count=len(categories.unchanged),
        source_document_count=len(categories.new)
        + len(categories.changed)
        + len(categories.unchanged),
        existing_document_count=len(categories.changed)
        + len(categories.unchanged)
        + len(categories.deleted),
        document_changes=document_changes,
    )


async def _publish_source_stats(
    callback: RagBuildStatsCallback | None,
    categories: DocumentCategories,
    model_type_name: str,
    doc_type: DocumentType,
) -> None:
    if callback is None:
        return
    await callback(_build_source_stats(categories, model_type_name, doc_type))


def _source_id_overrides_for_existing_documents(
    source_docs: Sequence[BaseRagModel], db_docs: Mapping[int, Document]
) -> dict[str, int]:
    db_id_by_source_key = {doc.source_key: doc.id_ for doc in db_docs.values()}
    overrides: dict[str, int] = {}
    for source_doc in source_docs:
        snapshot = _document_snapshot_from_source(source_doc)
        existing_source_id = db_id_by_source_key.get(snapshot.source_key)
        if existing_source_id is not None:
            overrides[snapshot.source_key] = existing_source_id
    return overrides


async def _process_new_documents(
    openai: AsyncAzureOpenAI,
    session: AsyncSession,
    new_docs: list[BaseRagModel],
    text_splitter: RecursiveCharacterTextSplitter,
    model_type_name: str,
) -> None:
    """Process and insert new documents into the database."""
    if not new_docs:
        return

    with telemetry.span("rag.process_new_documents") as span:
        span.set_attribute("app.rag.document_count", len(new_docs))
        span.set_attribute("app.rag.document_type_name", model_type_name)
        await _process_documents(openai, session, new_docs, text_splitter, model_type_name)


async def _process_changed_documents(
    openai: AsyncAzureOpenAI,
    session: AsyncSession,
    changed_docs: list[tuple[BaseRagModel, Document]],
    text_splitter: RecursiveCharacterTextSplitter,
    model_type_name: str,
) -> None:
    """Process changed documents by updating existing records."""
    if not changed_docs:
        return

    with telemetry.span("rag.process_changed_documents") as span:
        span.set_attribute("app.rag.document_count", len(changed_docs))
        span.set_attribute("app.rag.document_type_name", model_type_name)
        # Prepare document data with chunks
        source_docs = [source_doc for source_doc, _db_doc in changed_docs]
        source_id_overrides = _source_id_overrides_for_existing_documents(
            source_docs, {db_doc.id_: db_doc for _source_doc, db_doc in changed_docs}
        )
        document_data_list = await _prepare_document_data(
            source_docs, text_splitter, model_type_name, source_id_overrides=source_id_overrides
        )

        # Create embeddings
        document_data_with_embeddings = await _create_embeddings_for_documents(
            openai, document_data_list
        )

        # Update documents in database
        for doc_data, chunk_data in document_data_with_embeddings:
            # Find existing document
            result = await session.execute(
                select(Document).where(
                    Document.type == doc_data["type"], Document.id_ == doc_data["id_"]
                )
            )
            existing_doc = result.scalar_one_or_none()

            if existing_doc:
                # Delete old chunks (cascade will handle this, but being explicit)
                await session.execute(
                    delete(DocumentContentChunk).where(
                        DocumentContentChunk.document_id == existing_doc.id
                    )
                )

                # Update document fields
                existing_doc.source_key = doc_data["source_key"]
                existing_doc.title = doc_data["title"]
                existing_doc.url = doc_data["url"]
                existing_doc.markdown_content = doc_data["markdown_content"]
                existing_doc.token_count = doc_data["token_count"]
                existing_doc.character_count = doc_data["character_count"]
                existing_doc.title_embedding = doc_data["title_embedding"]  # type: ignore[assignment]
                existing_doc.school = doc_data["school"]  # type: ignore[assignment]
                existing_doc.source_created_at = doc_data["source_created_at"]  # type: ignore[assignment]
                existing_doc.source_updated_at = doc_data["source_updated_at"]  # type: ignore[assignment]

                await session.flush()

                # Insert new chunks
                for seq_num, content, token_count, character_count, embedding in chunk_data:
                    chunk = DocumentContentChunk(
                        sequence_number=seq_num,
                        content=content,
                        token_count=token_count,
                        character_count=character_count,
                        content_embedding=embedding,
                        document_id=existing_doc.id,
                    )
                    session.add(chunk)

        telemetry.info(
            "Updated {count} {type} documents", count=len(changed_docs), type=model_type_name
        )


async def _process_deleted_documents(
    session: AsyncSession, deleted_docs: list[Document], model_type_name: str
) -> None:
    """Delete documents that no longer exist in source data."""
    if not deleted_docs:
        return

    with telemetry.span("rag.delete_documents") as span:
        span.set_attribute("app.rag.document_count", len(deleted_docs))
        span.set_attribute("app.rag.document_type_name", model_type_name)
        for doc in deleted_docs:
            await session.delete(doc)
        await session.flush()

        telemetry.info(
            "Deleted {count} {type} documents", count=len(deleted_docs), type=model_type_name
        )


def _log_dry_run_stats(categories: DocumentCategories, model_type_name: str) -> None:
    """Log statistics for dry-run mode."""
    telemetry.info(
        "[DRY RUN] {type}: {new} new, {changed} changed, {deleted} deleted, {unchanged} unchanged",
        type=model_type_name,
        new=len(categories.new),
        changed=len(categories.changed),
        deleted=len(categories.deleted),
        unchanged=len(categories.unchanged),
    )


def _log_update_stats(categories: DocumentCategories, model_type_name: str) -> None:
    """Log statistics for actual update."""
    telemetry.info(
        "{type}: {new} new, {changed} changed, {deleted} deleted, {unchanged} unchanged",
        type=model_type_name,
        new=len(categories.new),
        changed=len(categories.changed),
        deleted=len(categories.deleted),
        unchanged=len(categories.unchanged),
    )


async def build_search_db(
    openai: AsyncAzureOpenAI,
    session: AsyncSession,
    *,
    force_rebuild: bool = False,
    dry_run: bool = False,
    source_stats_callback: RagBuildStatsCallback | None = None,
) -> None:
    """Build or update the search database.

    This function supports two modes:

    1. **Incremental Update (default)**: Compares source documents with the database
       and only processes new, changed, or deleted documents. This is significantly
       faster and more cost-effective for large datasets where most documents are
       unchanged between runs.

       The incremental update works in three phases:
       - Phase 1 (Discovery): Load source documents and existing DB documents,
         then categorize each document as NEW, CHANGED, UNCHANGED, or DELETED
         by stable source_key first, falling back to source id, then comparing
         source_updated_at timestamps for reliable upstream sources or rendered
         DB payloads for synthetic PDFs, standalone synthetic calendars, and
         training materials.
       - Phase 2 (Update): Process only the documents that need updates:
         * DELETED: Remove from database first to free stable source keys
         * CHANGED: Delete old chunks, update document, create new embeddings
         * NEW: Create embeddings and insert into database
         * UNCHANGED: Skip entirely (no processing)
       - Phase 3 (Commit): Save all changes in a single atomic transaction

       Performance: For a typical update with 1000 total documents where 50 are new,
       20 changed, and 10 deleted, this provides ~12.5x speedup by only processing
       80 documents instead of 1000.

    2. **Full Rebuild (--force-rebuild)**: Deletes all documents and recreates
       from scratch. Use this when:
       - Database schema has changed
       - Embedding model has changed
       - You want to ensure a clean slate
       - There are data inconsistencies

    Args:
        openai: OpenAI client for creating embeddings
        force_rebuild: If True, delete all documents and rebuild from scratch
        dry_run: If True, only preview changes without committing to database.
                 Useful for checking what would be updated before running the actual update.
        source_stats_callback: Optional async callback that receives per-source change counts
                 and document identities after source/DB comparison.
        session: Explicit database session to use for the rebuild.

    Examples:
        # Incremental update (default, recommended)
        python -m app.rag.build

        # Preview changes without committing
        python -m app.rag.build --dry-run

        # Force full rebuild
        python -m app.rag.build --force-rebuild

        # Preview full rebuild
        python -m app.rag.build --force-rebuild --dry-run

    """
    rebuild_mode = "full_rebuild" if force_rebuild else "incremental_update"
    with telemetry.span("rag.build_search_db") as span:
        span.set_attribute("app.rag.force_rebuild", force_rebuild)
        span.set_attribute("app.rag.dry_run", dry_run)
        span.set_attribute("app.rag.rebuild_mode", rebuild_mode)
        demo_stats = write_demo_rag_data()
        span.set_attribute("app.rag.demo_corpus_document_count", demo_stats.total_documents)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len
        )

        if force_rebuild:
            # Full rebuild: snapshot the previous index before deleting and recreating rows.
            telemetry.info("Performing full rebuild - deleting all documents")
            document_sources = _get_document_sources()
            existing_docs_by_type = {
                doc_type: await _load_existing_documents(session, doc_type)
                for _loader, _name, doc_type in document_sources
            }
            if not dry_run:
                await session.execute(delete(Document))

            for loader, name, doc_type in document_sources:
                with telemetry.span("rag.process_document_source") as source_span:
                    source_span.set_attribute("app.rag.document_source_name", name)
                    source_span.set_attribute("app.rag.document_type", doc_type.value)
                    source_docs = list(loader())
                    existing_docs = existing_docs_by_type[doc_type]
                    categories = _categorize_documents(source_docs, existing_docs)
                    await _publish_source_stats(source_stats_callback, categories, name, doc_type)
                    if dry_run:
                        _log_dry_run_stats(categories, name)
                        telemetry.info(
                            "[DRY RUN] Would process {count} {type} documents",
                            count=len(source_docs),
                            type=name,
                        )
                    else:
                        await _process_documents(
                            openai,
                            session,
                            source_docs,
                            text_splitter,
                            name,
                            source_id_overrides=_source_id_overrides_for_existing_documents(
                                source_docs, existing_docs
                            ),
                        )
        else:
            # Incremental update: compare and update only changed documents
            telemetry.info("Performing incremental update")

            for loader, name, doc_type in _get_document_sources():
                with telemetry.span("rag.process_document_source") as source_span:
                    source_span.set_attribute("app.rag.document_source_name", name)
                    source_span.set_attribute("app.rag.document_type", doc_type.value)
                    # Phase 1: Discovery - load and categorize documents
                    source_docs = list(loader())
                    db_docs = await _load_existing_documents(session, doc_type)
                    categories = _categorize_documents(source_docs, db_docs)
                    await _publish_source_stats(source_stats_callback, categories, name, doc_type)

                    if dry_run:
                        # Just log what would happen
                        _log_dry_run_stats(categories, name)
                    else:
                        # Phase 2: Update - delete obsolete rows before updates/inserts so
                        # stable source-key migrations can replace older source ids.
                        await _process_deleted_documents(session, categories.deleted, name)
                        await _process_changed_documents(
                            openai, session, categories.changed, text_splitter, name
                        )
                        await _process_new_documents(
                            openai, session, categories.new, text_splitter, name
                        )

                        # Log stats
                        _log_update_stats(categories, name)

        # Phase 3: Commit - save all changes atomically
        if not dry_run:
            await refresh_guardrail_url_registries(session)
            await session.commit()
            telemetry.info("Database changes committed successfully")
        else:
            telemetry.info("DRY RUN complete - no changes committed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or update the search database with document embeddings"
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force a full rebuild by deleting all documents and recreating from scratch",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing to database (shows what would be "
        "added/changed/deleted)",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    async with get_session() as session:
        await build_search_db(
            get_azure_openai_client(),
            session,
            force_rebuild=args.force_rebuild,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    asyncio.run(_main())
