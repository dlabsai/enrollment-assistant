import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.deps import Deps
from app.chat.tools.models import (
    Document,
    DocumentChunkResult,
    DocumentTitleResult,
    DocumentType,
    FindDocumentChunksDedupeSummary,
    FindDocumentChunksResultItem,
    NotFoundIds,
    TruncatedDocInfo,
)
from app.models import Document as DBDocument
from app.models import DocumentContentChunk
from app.otel_genai import (
    set_embedding_response_attributes,
    start_genai_embeddings_span,
    start_genai_retrieval_span,
    start_genai_tool_span,
)
from app.rag.constants import EMBEDDING_MODEL, EMBEDDING_VECTOR_DIMENSIONS
from app.rag.document_exclusions import append_va_document_exclusion_filter
from app.rag.training_materials.urls import (
    training_material_demo_url_from_url,
    training_material_path_from_url,
)
from app.tokens import count_tokens, get_encoding

_RETRIEVE_DOCUMENTS_MAX_TOKENS = 64_000
_RETRIEVE_DOCUMENTS_MAX_DOCUMENT_TOKENS = 32_000
_FIND_DOCUMENT_TITLES_MAX_RESULTS = 100
_FIND_DOCUMENT_CHUNKS_MAX_RESULTS = 50
_FIND_DOCUMENT_CHUNKS_OVERFETCH_MULTIPLIER = 3
_FIND_DOCUMENT_CHUNKS_INLINE_SOURCE_LIMIT = 100
_FIND_DOCUMENT_CHUNKS_SCHEMA = "find_document_chunks.v2"
_FIND_DOCUMENT_CHUNKS_SCHEMA_ATTRIBUTE = "app.document_tool.find_document_chunks.schema"
_FIND_DOCUMENT_CHUNKS_DEDUPE_ATTRIBUTE = "app.document_tool.find_document_chunks.dedupe"
_FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE = (
    "app.document_tool.find_document_chunks.full_provenance"
)
_RAG_DATA_SOURCE_ID = "demo-rag"

logger = logging.getLogger("demo-va")

_INTERNAL_ONLY_TYPES = (DocumentType.TRAINING_MATERIAL,)


def _allowed_document_types_for_search(*, is_internal: bool) -> tuple[DocumentType, ...]:
    allowed_types = list(DocumentType)
    if not is_internal:
        allowed_types = [
            doc_type for doc_type in allowed_types if doc_type not in _INTERNAL_ONLY_TYPES
        ]
    return tuple(allowed_types)


def _effective_document_types_for_search(
    document_types: list[DocumentType] | None, *, is_internal: bool
) -> tuple[DocumentType, ...]:
    allowed_types = _allowed_document_types_for_search(is_internal=is_internal)
    if document_types is None:
        return allowed_types

    requested_types = tuple(dict.fromkeys(document_types))
    return tuple(doc_type for doc_type in requested_types if doc_type in allowed_types)


def _document_types_tool_payload(document_types: list[DocumentType] | None) -> list[str] | None:
    if document_types is None:
        return None
    return [doc_type.value for doc_type in document_types]


def _document_result_payload(results: list[Document] | list[FindDocumentChunksResultItem]) -> str:
    payload: list[dict[str, Any]] = [result.model_dump(mode="json") for result in results]
    return json.dumps(payload, ensure_ascii=False)


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _format_document_title_results(results: list[DocumentTitleResult]) -> str:
    if not results:
        return "No matching document titles found."
    lines = ["| id | type | title |", "|---:|---|---|"]
    lines.extend(
        "| "
        f"{result.id} | "
        f"{_escape_markdown_table_cell(result.type.value)} | "
        f"{_escape_markdown_table_cell(result.title)} |"
        for result in results
    )
    return "\n".join(lines)


def _document_tool_input_payload(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _retrieval_document_id(result: DocumentChunkResult | DocumentTitleResult) -> str:
    if isinstance(result, DocumentChunkResult):
        return f"{result.type.value}:{result.id}:chunk:{result.sequence_number}"
    return f"{result.type.value}:{result.id}"


def _retrieval_documents_payload(
    results: list[DocumentChunkResult] | list[DocumentTitleResult],
) -> str:
    return json.dumps(
        [{"id": _retrieval_document_id(result)} for result in results], ensure_ascii=False
    )


def _set_document_tool_span_arguments(span: Any, input_payload: str) -> None:
    span.set_attribute("gen_ai.tool.call.arguments", input_payload)


def _set_document_tool_span_result(
    span: Any,
    *,
    results: list[Document] | list[FindDocumentChunksResultItem],
    not_found_ids: NotFoundIds | None = None,
    truncated_info: TruncatedDocInfo | None = None,
) -> None:
    span.set_attribute("gen_ai.tool.call.result", _document_result_payload(results))
    if not_found_ids is not None:
        span.set_attribute("app.document_tool.not_found_ids", not_found_ids.model_dump_json())
    if truncated_info is not None:
        span.set_attribute("app.document_tool.truncated_info", truncated_info.model_dump_json())


type _TrainingMaterialTreeNode = dict[str, "_TrainingMaterialTreeNode | tuple[int, str] | None"]


def _format_training_material_tree_label(value: str) -> str:
    normalized = "".join(
        " " if character.isspace() or unicodedata.category(character).startswith("C") else character
        for character in value
    )
    collapsed = re.sub(r" {2,}", " ", normalized).strip()
    label = collapsed or "untitled"
    return re.sub(r"^(\d+)\.\s", r"\1\\. ", label)


def _render_training_materials_tree(rows: list[tuple[int, str, str]]) -> str:
    tree: _TrainingMaterialTreeNode = {}
    for document_id, title, source_path in sorted(rows, key=lambda item: item[2]):
        parts = [part for part in source_path.split("/") if part]
        if not parts:
            continue
        node = tree
        for part in parts[:-1]:
            child = node.get(part)
            if child is None or isinstance(child, tuple):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = (document_id, title)

    def render_node(node: _TrainingMaterialTreeNode, *, indent: int = 0) -> list[str]:
        lines: list[str] = []
        for key, value in sorted(node.items()):
            prefix = "  " * indent
            label = _format_training_material_tree_label(key)
            if isinstance(value, dict):
                lines.append(f"{prefix}- {label}/")
                lines.extend(render_node(value, indent=indent + 1))
            elif isinstance(value, tuple):
                document_id, _title = value
                lines.append(f"{prefix}- [{document_id}] {label}")
            else:
                lines.append(f"{prefix}- {label}")
        return lines

    return "\n".join(render_node(tree))


def _set_retrieval_span_attributes(
    span: Any,
    *,
    query: str,
    top_k: int,
    results: list[DocumentChunkResult] | list[DocumentTitleResult],
) -> None:
    span.set_attribute("gen_ai.operation.name", "retrieval")
    span.set_attribute("gen_ai.data_source.id", "demo-rag")
    span.set_attribute("gen_ai.retrieval.query.text", query)
    span.set_attribute("gen_ai.request.top_k", top_k)
    span.set_attribute("gen_ai.retrieval.documents", _retrieval_documents_payload(results))


@dataclass(frozen=True)
class _DocumentChunkCandidate:
    content: str
    sequence_number: int
    document_type: DocumentType
    document_id: int
    title: str


@dataclass
class _DocumentChunkSourceLocation:
    document_type: DocumentType
    document_id: int
    title: str
    first_rank: int
    sequence_numbers: set[int]


@dataclass
class _DocumentChunkGroup:
    content_hash: str
    content: str
    first_rank: int
    representative: _DocumentChunkCandidate
    occurrences: int
    sources: dict[tuple[DocumentType, int], _DocumentChunkSourceLocation]


@dataclass(frozen=True)
class _FindDocumentChunksDbPayload:
    result: list[FindDocumentChunksResultItem]
    dedupe: FindDocumentChunksDedupeSummary
    full_provenance: dict[str, Any]
    representative_results: list[DocumentChunkResult]


def _find_document_chunks_candidate_limit(effective_limit: int) -> int:
    return effective_limit * _FIND_DOCUMENT_CHUNKS_OVERFETCH_MULTIPLIER


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _serialize_chunk_sources(
    sources: dict[tuple[DocumentType, int], _DocumentChunkSourceLocation],
    *,
    source_limit: int | None,
) -> dict[str, list[tuple[int, list[int], str]]]:
    ordered_sources = sorted(sources.values(), key=lambda source: source.first_rank)
    included_sources = ordered_sources if source_limit is None else ordered_sources[:source_limit]

    payload: dict[str, list[tuple[int, list[int], str]]] = {}
    for source in included_sources:
        payload.setdefault(source.document_type.value, []).append(
            (source.document_id, sorted(source.sequence_numbers), source.title)
        )
    return payload


def _find_document_chunks_empty_payload(*, effective_limit: int) -> _FindDocumentChunksDbPayload:
    result: list[FindDocumentChunksResultItem] = []
    dedupe = FindDocumentChunksDedupeSummary(
        effective_limit=effective_limit,
        candidate_count=0,
        unique_candidates=0,
        unique_results=0,
        candidate_collapsed_occurrences=0,
        returned_collapsed_occurrences=0,
        omitted_candidate_collapsed_occurrences=0,
    )
    return _FindDocumentChunksDbPayload(
        result=result,
        dedupe=dedupe,
        full_provenance={"schema": _FIND_DOCUMENT_CHUNKS_SCHEMA, "results": []},
        representative_results=[],
    )


def _build_find_document_chunks_payload(
    candidates: list[_DocumentChunkCandidate],
    *,
    effective_limit: int,
    inline_source_limit: int = _FIND_DOCUMENT_CHUNKS_INLINE_SOURCE_LIMIT,
) -> _FindDocumentChunksDbPayload:
    groups_by_hash: dict[str, _DocumentChunkGroup] = {}
    ordered_groups: list[_DocumentChunkGroup] = []

    for rank, candidate in enumerate(candidates):
        hash_value = _content_hash(candidate.content)
        group = groups_by_hash.get(hash_value)
        if group is None:
            group = _DocumentChunkGroup(
                content_hash=hash_value,
                content=candidate.content,
                first_rank=rank,
                representative=candidate,
                occurrences=0,
                sources={},
            )
            groups_by_hash[hash_value] = group
            ordered_groups.append(group)

        group.occurrences += 1
        source_key = (candidate.document_type, candidate.document_id)
        source = group.sources.get(source_key)
        if source is None:
            source = _DocumentChunkSourceLocation(
                document_type=candidate.document_type,
                document_id=candidate.document_id,
                title=candidate.title,
                first_rank=rank,
                sequence_numbers=set(),
            )
            group.sources[source_key] = source
        source.sequence_numbers.add(candidate.sequence_number)

    ordered_groups.sort(key=lambda group: group.first_rank)
    returned_groups = ordered_groups[:effective_limit]

    result_items: list[FindDocumentChunksResultItem] = []
    full_provenance_results: list[dict[str, Any]] = []
    representative_results: list[DocumentChunkResult] = []
    for result_index, group in enumerate(returned_groups):
        inline_sources = _serialize_chunk_sources(group.sources, source_limit=inline_source_limit)
        full_sources = _serialize_chunk_sources(group.sources, source_limit=None)
        result_items.append(
            FindDocumentChunksResultItem(content=group.content, sources=inline_sources)
        )
        full_provenance_results.append(
            {
                "result_index": result_index,
                "content_hash": group.content_hash,
                "sources": full_sources,
                "occurrences": group.occurrences,
                "source_documents": len(group.sources),
            }
        )
        representative_results.append(
            DocumentChunkResult(
                type=group.representative.document_type,
                id=group.representative.document_id,
                title=group.representative.title,
                sequence_number=group.representative.sequence_number,
                content=group.representative.content,
            )
        )

    candidate_collapsed_occurrences = sum(group.occurrences - 1 for group in ordered_groups)
    returned_collapsed_occurrences = sum(group.occurrences - 1 for group in returned_groups)
    dedupe = FindDocumentChunksDedupeSummary(
        effective_limit=effective_limit,
        candidate_count=len(candidates),
        unique_candidates=len(ordered_groups),
        unique_results=len(result_items),
        candidate_collapsed_occurrences=candidate_collapsed_occurrences,
        returned_collapsed_occurrences=returned_collapsed_occurrences,
        omitted_candidate_collapsed_occurrences=(
            candidate_collapsed_occurrences - returned_collapsed_occurrences
        ),
    )
    return _FindDocumentChunksDbPayload(
        result=result_items,
        dedupe=dedupe,
        full_provenance={
            "schema": _FIND_DOCUMENT_CHUNKS_SCHEMA,
            "results": full_provenance_results,
        },
        representative_results=representative_results,
    )


def _truncate_to_token_limit(text: str, token_limit: int) -> tuple[str, int, int]:
    encoding = get_encoding()
    original_tokens = count_tokens(text)

    if original_tokens <= token_limit:
        return text, original_tokens, original_tokens

    truncated_content = encoding.decode(encoding.encode(text)[:token_limit])
    truncated_tokens = count_tokens(truncated_content)

    return truncated_content, original_tokens, truncated_tokens


async def _retrieve_documents_db(
    session: AsyncSession,
    website_page_ids: list[int] | None = None,
    website_program_ids: list[int] | None = None,
    catalog_page_ids: list[int] | None = None,
    catalog_program_ids: list[int] | None = None,
    catalog_course_ids: list[int] | None = None,
    training_material_ids: list[int] | None = None,
) -> tuple[list[Document], NotFoundIds | None, TruncatedDocInfo | None]:
    logger.info(
        "retrieve documents: website_page_ids=%s website_program_ids=%s "
        "catalog_page_ids=%s catalog_program_ids=%s catalog_course_ids=%s "
        "training_material_ids=%s",
        website_page_ids,
        website_program_ids,
        catalog_page_ids,
        catalog_program_ids,
        catalog_course_ids,
        training_material_ids,
    )

    documents: list[Document] = []
    not_found_ids = NotFoundIds()
    truncated_info = TruncatedDocInfo()
    total_tokens = 0
    all_documents: list[Document] = []

    query_criteria: list[tuple[DocumentType, list[int]]] = []
    if website_page_ids:
        query_criteria.append((DocumentType.WEBSITE_PAGE, website_page_ids))
    if website_program_ids:
        query_criteria.append((DocumentType.WEBSITE_PROGRAM, website_program_ids))
    if catalog_page_ids:
        query_criteria.append((DocumentType.CATALOG_PAGE, catalog_page_ids))
    if catalog_program_ids:
        query_criteria.append((DocumentType.CATALOG_PROGRAM, catalog_program_ids))
    if catalog_course_ids:
        query_criteria.append((DocumentType.CATALOG_COURSE, catalog_course_ids))
    if training_material_ids:
        query_criteria.append((DocumentType.TRAINING_MATERIAL, training_material_ids))

    for doc_type, doc_ids in query_criteria:
        conditions: list[Any] = [DBDocument.type == doc_type, DBDocument.id_.in_(doc_ids)]
        append_va_document_exclusion_filter(conditions)
        stmt = select(DBDocument).where(*conditions)
        result = await session.execute(stmt)
        db_docs = result.scalars().all()

        found_ids = {doc.id_ for doc in db_docs}
        not_found = [doc_id for doc_id in doc_ids if doc_id not in found_ids]

        if not_found:
            if doc_type == DocumentType.WEBSITE_PAGE:
                not_found_ids.not_found_website_page = not_found
            elif doc_type == DocumentType.WEBSITE_PROGRAM:
                not_found_ids.not_found_website_program = not_found
            elif doc_type == DocumentType.CATALOG_PAGE:
                not_found_ids.not_found_catalog_page = not_found
            elif doc_type == DocumentType.CATALOG_PROGRAM:
                not_found_ids.not_found_catalog_program = not_found
            elif doc_type == DocumentType.CATALOG_COURSE:
                not_found_ids.not_found_catalog_course = not_found
            elif doc_type == DocumentType.TRAINING_MATERIAL:
                not_found_ids.not_found_training_material = not_found

        for db_doc in db_docs:
            all_documents.append(
                Document(
                    type=db_doc.type,
                    id=db_doc.id_,
                    title=db_doc.title,
                    url=(
                        training_material_demo_url_from_url(db_doc.url)
                        if db_doc.type == DocumentType.TRAINING_MATERIAL
                        else db_doc.url
                    ),
                    content=db_doc.markdown_content,
                    updated_at=db_doc.source_updated_at,
                )
            )

    has_not_found_ids = (
        bool(not_found_ids.not_found_website_page)
        or bool(not_found_ids.not_found_website_program)
        or bool(not_found_ids.not_found_catalog_page)
        or bool(not_found_ids.not_found_catalog_program)
        or bool(not_found_ids.not_found_catalog_course)
        or bool(not_found_ids.not_found_training_material)
    )

    has_truncation = False

    for doc in all_documents:
        doc_tokens = count_tokens(doc.content)
        doc_to_add = doc
        was_truncated = False

        if doc_tokens > _RETRIEVE_DOCUMENTS_MAX_DOCUMENT_TOKENS:
            truncated_content, original_tokens, truncated_tokens = _truncate_to_token_limit(
                doc.content, _RETRIEVE_DOCUMENTS_MAX_DOCUMENT_TOKENS
            )
            percentage_preserved = round((truncated_tokens / original_tokens) * 100, 1)

            truncated_content += (
                "\n\n[Content truncated due to document size limit. "
                f"{percentage_preserved}% of original content preserved.]"
            )

            doc_to_add = Document(
                type=doc.type,
                id=doc.id,
                title=doc.title,
                url=doc.url,
                content=truncated_content,
                updated_at=doc.updated_at,
            )

            was_truncated = True
            has_truncation = True
            doc_tokens = count_tokens(truncated_content)

        if total_tokens + doc_tokens > _RETRIEVE_DOCUMENTS_MAX_TOKENS:
            remaining_tokens = _RETRIEVE_DOCUMENTS_MAX_TOKENS - total_tokens
            if remaining_tokens > 100:  # noqa: PLR2004
                truncated_content, original_tokens, truncated_tokens = _truncate_to_token_limit(
                    doc_to_add.content, remaining_tokens
                )
                percentage_preserved = round((truncated_tokens / original_tokens) * 100, 1)

                truncated_content += (
                    "\n\n[Content truncated due to global token limit. "
                    f"{percentage_preserved}% of original content preserved.]"
                )

                doc_to_add.content = truncated_content
                documents.append(doc_to_add)
                truncated_info.truncated_docs.append((doc.type, doc.id, doc.title))
                has_truncation = True
                total_tokens = _RETRIEVE_DOCUMENTS_MAX_TOKENS
            else:
                truncated_info.omitted_docs.append((doc.type, doc.id, doc.title))
                has_truncation = True
        else:
            documents.append(doc_to_add)
            total_tokens += doc_tokens
            if was_truncated:
                truncated_info.truncated_docs.append((doc.type, doc.id, doc.title))

    return (
        documents,
        not_found_ids if has_not_found_ids else None,
        truncated_info if has_truncation else None,
    )


async def _find_document_chunks_db(
    session: AsyncSession,
    openai: AsyncAzureOpenAI | AsyncOpenAI,
    content_search_query: str,
    *,
    is_internal: bool = False,
    document_types: list[DocumentType] | None = None,
) -> _FindDocumentChunksDbPayload:
    effective_limit = _FIND_DOCUMENT_CHUNKS_MAX_RESULTS
    effective_document_types = _effective_document_types_for_search(
        document_types, is_internal=is_internal
    )
    if not effective_document_types:
        return _find_document_chunks_empty_payload(effective_limit=effective_limit)

    with start_genai_embeddings_span(EMBEDDING_MODEL) as span:
        embedding = await openai.embeddings.create(
            input=content_search_query,
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_VECTOR_DIMENSIONS,
        )
        set_embedding_response_attributes(span, embedding, model=EMBEDDING_MODEL)

    assert len(embedding.data) == 1, (
        f"Expected 1 embedding, got {len(embedding.data)}, doc query: {content_search_query!r}"
    )
    embedding = embedding.data[0].embedding
    content_distance = DocumentContentChunk.content_embedding.l2_distance(embedding)

    stmt = (
        select(
            DocumentContentChunk.content,
            DocumentContentChunk.sequence_number,
            DBDocument.type.label("document_type"),
            DBDocument.id_.label("document_id"),
            DBDocument.title.label("title"),
        )
        .join(DBDocument, DocumentContentChunk.document_id == DBDocument.id)
        .order_by(content_distance)
    )
    stmt = stmt.where(DBDocument.type.in_(effective_document_types))
    conditions: list[Any] = []
    append_va_document_exclusion_filter(conditions)
    stmt = stmt.where(*conditions).limit(_find_document_chunks_candidate_limit(effective_limit))
    result = await session.execute(stmt)
    rows = result.all()
    candidates = [
        _DocumentChunkCandidate(
            content=row.content,
            sequence_number=row.sequence_number,
            document_type=row.document_type,
            document_id=row.document_id,
            title=row.title,
        )
        for row in rows
    ]

    return _build_find_document_chunks_payload(candidates, effective_limit=effective_limit)


async def _find_document_titles_db(
    session: AsyncSession,
    openai: AsyncAzureOpenAI | AsyncOpenAI,
    title_search_query: str,
    *,
    is_internal: bool = False,
    document_types: list[DocumentType] | None = None,
) -> list[DocumentTitleResult]:
    effective_document_types = _effective_document_types_for_search(
        document_types, is_internal=is_internal
    )
    if not effective_document_types:
        return []

    with start_genai_embeddings_span(EMBEDDING_MODEL) as span:
        embedding = await openai.embeddings.create(
            input=title_search_query, model=EMBEDDING_MODEL, dimensions=EMBEDDING_VECTOR_DIMENSIONS
        )
        set_embedding_response_attributes(span, embedding, model=EMBEDDING_MODEL)

    assert len(embedding.data) == 1, (
        f"Expected 1 embedding, got {len(embedding.data)}, doc query: {title_search_query!r}"
    )
    embedding = embedding.data[0].embedding

    stmt = select(DBDocument.title, DBDocument.type, DBDocument.id_, DBDocument.url).order_by(
        DBDocument.title_embedding.l2_distance(embedding)
    )
    stmt = stmt.where(DBDocument.type.in_(effective_document_types))
    conditions: list[Any] = []
    append_va_document_exclusion_filter(conditions)
    stmt = stmt.where(*conditions)
    stmt = stmt.limit(_FIND_DOCUMENT_TITLES_MAX_RESULTS)
    result = await session.execute(stmt)
    rows = result.all()

    return [
        DocumentTitleResult(
            title=(
                training_material_path_from_url(row.url)
                if row.type == DocumentType.TRAINING_MATERIAL
                else row.title
            ),
            type=row.type,
            id=row.id_,
        )
        for row in rows
    ]


# PydanticAI tool wrappers with ctx argument and docstrings


async def retrieve_documents(
    ctx: RunContext[Deps],
    website_page_ids: list[int] | None = None,
    website_program_ids: list[int] | None = None,
    catalog_page_ids: list[int] | None = None,
    catalog_program_ids: list[int] | None = None,
    catalog_course_ids: list[int] | None = None,
) -> tuple[list[Document], NotFoundIds | None, TruncatedDocInfo | None]:
    """Retrieve full website and catalog document content by IDs.

    Use other tools to get IDs first.
    """
    with start_genai_tool_span("retrieve_documents", tool_type="datastore") as span:
        _set_document_tool_span_arguments(
            span,
            _document_tool_input_payload(
                website_page_ids=website_page_ids,
                website_program_ids=website_program_ids,
                catalog_page_ids=catalog_page_ids,
                catalog_program_ids=catalog_program_ids,
                catalog_course_ids=catalog_course_ids,
            ),
        )
        async with ctx.deps.open_tool_session() as session:
            documents, not_found_ids, truncated_info = await _retrieve_documents_db(
                session,
                website_page_ids=website_page_ids,
                website_program_ids=website_program_ids,
                catalog_page_ids=catalog_page_ids,
                catalog_program_ids=catalog_program_ids,
                catalog_course_ids=catalog_course_ids,
            )
        _set_document_tool_span_result(
            span, results=documents, not_found_ids=not_found_ids, truncated_info=truncated_info
        )
        return documents, not_found_ids, truncated_info


async def retrieve_documents_internal(
    ctx: RunContext[Deps],
    website_page_ids: list[int] | None = None,
    website_program_ids: list[int] | None = None,
    catalog_page_ids: list[int] | None = None,
    catalog_program_ids: list[int] | None = None,
    catalog_course_ids: list[int] | None = None,
    training_material_ids: list[int] | None = None,
) -> tuple[list[Document], NotFoundIds | None, TruncatedDocInfo | None]:
    """Retrieve full website, catalog, and internal training-material document content by IDs."""
    with start_genai_tool_span("retrieve_documents", tool_type="datastore") as span:
        _set_document_tool_span_arguments(
            span,
            _document_tool_input_payload(
                website_page_ids=website_page_ids,
                website_program_ids=website_program_ids,
                catalog_page_ids=catalog_page_ids,
                catalog_program_ids=catalog_program_ids,
                catalog_course_ids=catalog_course_ids,
                training_material_ids=training_material_ids,
            ),
        )
        async with ctx.deps.open_tool_session() as session:
            documents, not_found_ids, truncated_info = await _retrieve_documents_db(
                session,
                website_page_ids=website_page_ids,
                website_program_ids=website_program_ids,
                catalog_page_ids=catalog_page_ids,
                catalog_program_ids=catalog_program_ids,
                catalog_course_ids=catalog_course_ids,
                training_material_ids=training_material_ids,
            )
        _set_document_tool_span_result(
            span, results=documents, not_found_ids=not_found_ids, truncated_info=truncated_info
        )
        return documents, not_found_ids, truncated_info


async def list_training_materials_tree(ctx: RunContext[Deps]) -> str:
    """List available internal training material documents as a Markdown folder tree."""
    with start_genai_tool_span("list_training_materials_tree", tool_type="datastore") as span:
        _set_document_tool_span_arguments(span, _document_tool_input_payload())
        async with ctx.deps.open_tool_session() as session:
            conditions: list[Any] = [DBDocument.type == DocumentType.TRAINING_MATERIAL]
            append_va_document_exclusion_filter(conditions)
            rows = (
                await session.execute(
                    select(DBDocument.id_, DBDocument.title, DBDocument.url).where(*conditions)
                )
            ).all()

        tree = _render_training_materials_tree(
            [(row.id_, row.title, training_material_path_from_url(row.url)) for row in rows]
        )
        result = (
            f"Document count: {len(rows)}\n\n{tree}" if tree else f"Document count: {len(rows)}"
        )
        span.set_attribute("gen_ai.tool.call.result", result)
        return result


async def _find_document_titles_tool(
    ctx: RunContext[Deps], title_search_query: str, document_types: list[DocumentType] | None = None
) -> str:
    with start_genai_tool_span("find_document_titles", tool_type="datastore") as span:
        argument_payload: dict[str, object] = {"title_search_query": title_search_query}
        if document_types is not None:
            argument_payload["document_types"] = _document_types_tool_payload(document_types)
        _set_document_tool_span_arguments(span, _document_tool_input_payload(**argument_payload))
        with start_genai_retrieval_span(
            data_source_id=_RAG_DATA_SOURCE_ID,
            query=title_search_query,
            top_k=_FIND_DOCUMENT_TITLES_MAX_RESULTS,
        ) as retrieval_span:
            async with ctx.deps.open_tool_session() as session:
                results = await _find_document_titles_db(
                    session,
                    ctx.deps.openai,
                    title_search_query,
                    is_internal=ctx.deps.is_internal,
                    document_types=document_types,
                )
            _set_retrieval_span_attributes(
                retrieval_span,
                query=title_search_query,
                top_k=_FIND_DOCUMENT_TITLES_MAX_RESULTS,
                results=results,
            )
        result_text = _format_document_title_results(results)
        span.set_attribute("gen_ai.tool.call.result", result_text)
        return result_text


async def find_document_titles(ctx: RunContext[Deps], title_search_query: str) -> str:
    """Retrieve public website and catalog document IDs and titles by vector similarity.

    Results are returned as an ordered Markdown table with id, type, and title columns. The order
    is by vector similarity in descending relevance.
    """
    return await _find_document_titles_tool(ctx, title_search_query)


async def find_document_titles_internal(
    ctx: RunContext[Deps], title_search_query: str, document_types: list[DocumentType] | None = None
) -> str:
    """Retrieve document IDs and titles by vector similarity.

    Optionally filter by document_types, such as ["training_material"],
    ["website_page", "website_program"], or catalog types. Results
    are returned as an ordered Markdown table with id, type, and title columns.
    """
    return await _find_document_titles_tool(ctx, title_search_query, document_types=document_types)


async def _find_document_chunks_tool(
    ctx: RunContext[Deps],
    content_search_query: str,
    document_types: list[DocumentType] | None = None,
) -> list[FindDocumentChunksResultItem]:
    effective_limit = _FIND_DOCUMENT_CHUNKS_MAX_RESULTS
    with start_genai_tool_span("find_document_chunks", tool_type="datastore") as span:
        argument_payload: dict[str, object] = {"content_search_query": content_search_query}
        if document_types is not None:
            argument_payload["document_types"] = _document_types_tool_payload(document_types)
        _set_document_tool_span_arguments(span, _document_tool_input_payload(**argument_payload))
        with start_genai_retrieval_span(
            data_source_id=_RAG_DATA_SOURCE_ID, query=content_search_query, top_k=effective_limit
        ) as retrieval_span:
            async with ctx.deps.open_tool_session() as session:
                db_payload = await _find_document_chunks_db(
                    session,
                    ctx.deps.openai,
                    content_search_query,
                    is_internal=ctx.deps.is_internal,
                    document_types=document_types,
                )
            _set_retrieval_span_attributes(
                retrieval_span,
                query=content_search_query,
                top_k=effective_limit,
                results=db_payload.representative_results,
            )
        _set_document_tool_span_result(span, results=db_payload.result)
        span.set_attribute(_FIND_DOCUMENT_CHUNKS_SCHEMA_ATTRIBUTE, _FIND_DOCUMENT_CHUNKS_SCHEMA)
        span.set_attribute(
            _FIND_DOCUMENT_CHUNKS_DEDUPE_ATTRIBUTE, db_payload.dedupe.model_dump_json()
        )
        span.set_attribute(
            _FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE,
            json.dumps(db_payload.full_provenance, ensure_ascii=False),
        )
        return db_payload.result


async def find_document_chunks(
    ctx: RunContext[Deps], content_search_query: str
) -> list[FindDocumentChunksResultItem]:
    """Retrieve exact-content-deduplicated public website and catalog document chunks.

    Results are sorted by best vector-similarity occurrence. Each unique chunk includes content
    plus grouped source locations shaped as source type ->
    [[document id, sequence numbers, title], ...].
    """
    return await _find_document_chunks_tool(ctx, content_search_query)


async def find_document_chunks_internal(
    ctx: RunContext[Deps],
    content_search_query: str,
    document_types: list[DocumentType] | None = None,
) -> list[FindDocumentChunksResultItem]:
    """Retrieve exact-content-deduplicated document text chunks.

    Optionally filter by document_types, such as ["training_material"],
    ["website_page", "website_program"], or catalog types. Results
    are sorted by best vector-similarity occurrence and include grouped source locations.
    """
    return await _find_document_chunks_tool(
        ctx, content_search_query, document_types=document_types
    )
