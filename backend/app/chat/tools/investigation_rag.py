from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import RunContext
from sqlalchemy import ColumnElement, desc, func, literal_column, or_, select

from app.chat.tools.deps import Deps
from app.models import Document, DocumentContentChunk, DocumentType, RagDocumentExclusion
from app.rag.constants import EMBEDDING_MODEL, EMBEDDING_VECTOR_DIMENSIONS
from app.rag.document_exclusions import RagExclusionFilter, apply_exclusion_filter

if TYPE_CHECKING:
    from collections.abc import Sequence

_SNIPPET_RADIUS_CHARS = 240
_FULL_TEXT_HEADLINE_OPTIONS = "MaxWords=60, MinWords=20, ShortWord=3"
_CONTENT_SEARCH_PAGE_SIZE_MAX = 200
_TITLE_SEARCH_PAGE_SIZE_MAX = 500
_DOCUMENT_PAGE_SIZE_MAX = 100


def _coerce_document_types(document_types: Sequence[str] | None) -> list[DocumentType] | None:
    if document_types is None:
        return None
    try:
        return [DocumentType(document_type) for document_type in document_types]
    except ValueError as error:
        valid_types = ", ".join(document_type.value for document_type in DocumentType)
        raise ValueError(f"Invalid document type. Valid values: {valid_types}") from error


def _coerce_bounded_positive(value: int, name: str, *, max_value: int) -> int:
    if value < 1:
        raise ValueError(f"{name} must be greater than or equal to 1")
    if value > max_value:
        raise ValueError(f"{name} must be less than or equal to {max_value}")
    return value


def _coerce_offset(offset: int) -> int:
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    return offset


async def _audit_embedding(ctx: RunContext[Deps], query: str) -> list[float]:
    embedding = await ctx.deps.openai.embeddings.create(
        input=query, model=EMBEDDING_MODEL, dimensions=EMBEDDING_VECTOR_DIMENSIONS
    )
    if len(embedding.data) != 1:
        raise ValueError(f"Expected 1 embedding, got {len(embedding.data)}")
    return embedding.data[0].embedding


async def _excluded_source_keys(
    ctx: RunContext[Deps],
    source_keys: Sequence[str],
    exclusion_filter: RagExclusionFilter | None = None,
) -> set[str]:
    if not source_keys or exclusion_filter == "included":
        return set()
    if exclusion_filter == "excluded":
        return set(source_keys)
    async with ctx.deps.open_tool_session() as session:
        rows = (
            (
                await session.execute(
                    select(RagDocumentExclusion.source_key).where(
                        RagDocumentExclusion.source_key.in_(source_keys)
                    )
                )
            )
            .scalars()
            .all()
        )
    return {str(source_key) for source_key in rows}


def _apply_document_filters(
    conditions: list[Any],
    *,
    document_types: Sequence[DocumentType] | None,
    exclusion_filter: RagExclusionFilter,
) -> None:
    if document_types is not None:
        conditions.append(Document.type.in_(document_types))
    apply_exclusion_filter(conditions, exclusion_filter)


def _content_snippet(content: str, query: str) -> str | None:
    match_index = content.lower().find(query.lower())
    if match_index < 0:
        return None
    start = max(0, match_index - _SNIPPET_RADIUS_CHARS)
    end = min(len(content), match_index + len(query) + _SNIPPET_RADIUS_CHARS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


def _matched_document_fields(document: Document, query: str) -> list[str]:
    query_lower = query.lower()
    fields = {
        "title": document.title,
        "url": document.url,
        "school": document.school or "",
        "content": document.markdown_content,
    }
    return [field for field, value in fields.items() if query_lower in value.lower()]


def _join_present(lines: Sequence[str | None]) -> str:
    return "\n".join(line for line in lines if line)


def _document_ref(document: Document) -> str:
    return f"{document.type.value}:{document.id_}"


def _document_heading(index: int, document: Document) -> str:
    return f"## {index}. {_document_ref(document)} — {document.title}"


def _document_metadata_lines(document: Document, *, excluded: bool = False) -> list[str | None]:
    return [
        f"url: {document.url}",
        f"school: {document.school}" if document.school else None,
        "excluded_from_va_rag: true" if excluded else None,
    ]


def _escape_table_cell(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _document_table(
    rows: Sequence[tuple[int, Document, bool, str | None]], *, include_rank: bool = False
) -> str:
    include_excluded = any(excluded for _index, _document, excluded, _rank in rows)
    headers = ["#", "doc", "title", "url"]
    if include_rank:
        headers.append("rank")
    if include_excluded:
        headers.append("excluded")
    lines = ["| " + " | ".join(headers) + " |", "|---:" + "|---" * (len(headers) - 1) + "|"]
    for index, document, excluded, rank in rows:
        values: list[object] = [index, _document_ref(document), document.title, document.url]
        if include_rank:
            values.append(rank or "")
        if include_excluded:
            values.append("yes" if excluded else "")
        lines.append("| " + " | ".join(_escape_table_cell(value) for value in values) + " |")
    return "\n".join(lines)


def _document_types_label(document_types: Sequence[DocumentType] | None) -> str:
    if document_types is None:
        return "all"
    return ", ".join(document_type.value for document_type in document_types)


def _pagination_lines(
    *, returned_count: int, total_count: int, page_size: int, offset: int
) -> list[str]:
    has_more = offset + returned_count < total_count
    lines = [
        f"returned_count: {returned_count}/{total_count}",
        f"page: size={page_size}; offset={offset}",
    ]
    if has_more:
        lines.append(f"next_offset: {offset + returned_count}")
    return lines


def _multiline_block(tag: str, content: str | None) -> str | None:
    if not content:
        return None
    return f"<{tag}>\n{content}\n</{tag}>"


async def audit_rag_content_search(
    ctx: RunContext[Deps],
    content_search_query: str,
    limit: int = 20,
    offset: int = 0,
    document_types: list[str] | None = None,
    exclusion_filter: RagExclusionFilter = "included",
) -> str:
    """Run diagnostic vector search over current RAG chunks.

    Returns full stored chunk text for vector-ranked chunks. This is not the normal VA chat tool;
    it is read-only corpus inspection. Use `offset`/`next_offset` to page through broader coverage.
    """
    limit = _coerce_bounded_positive(limit, "limit", max_value=_CONTENT_SEARCH_PAGE_SIZE_MAX)
    offset = _coerce_offset(offset)
    selected_types = _coerce_document_types(document_types)
    embedding = await _audit_embedding(ctx, content_search_query)

    async with ctx.deps.open_tool_session() as session:
        conditions: list[Any] = []
        _apply_document_filters(
            conditions, document_types=selected_types, exclusion_filter=exclusion_filter
        )
        total_count = await session.scalar(
            select(func.count())
            .select_from(DocumentContentChunk)
            .join(Document, DocumentContentChunk.document_id == Document.id)
            .where(*conditions)
        )
        rows = (
            await session.execute(
                select(
                    DocumentContentChunk.content,
                    DocumentContentChunk.sequence_number,
                    DocumentContentChunk.token_count.label("chunk_token_count"),
                    DocumentContentChunk.character_count.label("chunk_character_count"),
                    Document,
                )
                .join(Document, DocumentContentChunk.document_id == Document.id)
                .where(*conditions)
                .order_by(
                    DocumentContentChunk.content_embedding.l2_distance(embedding),
                    DocumentContentChunk.document_id.asc(),
                    DocumentContentChunk.sequence_number.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()

    total = total_count or 0
    excluded_source_keys = await _excluded_source_keys(
        ctx, [row.Document.source_key for row in rows], exclusion_filter
    )
    sections = [
        "# RAG content-search audit",
        _join_present(
            [
                f"query: {content_search_query}",
                f"document_types: {_document_types_label(selected_types)}",
                f"exclusion_filter: {exclusion_filter}",
                *_pagination_lines(
                    returned_count=len(rows), total_count=total, page_size=limit, offset=offset
                ),
                "note: vector-ranked page; continue with next_offset for more.",
            ]
        ),
    ]
    for index, row in enumerate(rows, start=1):
        sections.append(
            _join_present(
                [
                    _document_heading(offset + index, row.Document),
                    *_document_metadata_lines(
                        row.Document, excluded=row.Document.source_key in excluded_source_keys
                    ),
                    f"chunk_sequence: {row.sequence_number}",
                    f"chunk_tokens: {row.chunk_token_count}; "
                    f"chunk_chars: {row.chunk_character_count}",
                    _multiline_block("chunk", row.content),
                ]
            )
        )
    return "\n\n".join(sections)


async def audit_rag_title_search(
    ctx: RunContext[Deps],
    title_search_query: str,
    limit: int = 50,
    offset: int = 0,
    document_types: list[str] | None = None,
    exclusion_filter: RagExclusionFilter = "included",
) -> str:
    """Run paginated diagnostic vector search over current RAG document titles."""
    limit = _coerce_bounded_positive(limit, "limit", max_value=_TITLE_SEARCH_PAGE_SIZE_MAX)
    offset = _coerce_offset(offset)
    selected_types = _coerce_document_types(document_types)
    embedding = await _audit_embedding(ctx, title_search_query)

    async with ctx.deps.open_tool_session() as session:
        conditions: list[Any] = []
        _apply_document_filters(
            conditions, document_types=selected_types, exclusion_filter=exclusion_filter
        )
        total_count = await session.scalar(
            select(func.count()).select_from(Document).where(*conditions)
        )
        documents = (
            (
                await session.execute(
                    select(Document)
                    .where(*conditions)
                    .order_by(
                        Document.title_embedding.l2_distance(embedding),
                        Document.type.asc(),
                        Document.title.asc(),
                        Document.id_.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    total = total_count or 0
    excluded_source_keys = await _excluded_source_keys(
        ctx, [document.source_key for document in documents], exclusion_filter
    )
    sections = [
        "# RAG title-search audit",
        _join_present(
            [
                f"query: {title_search_query}",
                f"document_types: {_document_types_label(selected_types)}",
                f"exclusion_filter: {exclusion_filter}",
                *_pagination_lines(
                    returned_count=len(documents), total_count=total, page_size=limit, offset=offset
                ),
                "note: vector-ranked page; continue with next_offset for more.",
            ]
        ),
    ]
    sections.append(
        _document_table(
            [
                (offset + index, document, document.source_key in excluded_source_keys, None)
                for index, document in enumerate(documents, start=1)
            ]
        )
    )
    return "\n\n".join(sections)


async def list_rag_documents(
    ctx: RunContext[Deps],
    document_types: list[str] | None = None,
    page_size: int = 100,
    offset: int = 0,
    exclusion_filter: RagExclusionFilter = "included",
) -> str:
    """List indexed RAG document metadata with assistant-controlled pagination."""
    page_size = _coerce_bounded_positive(page_size, "page_size", max_value=_DOCUMENT_PAGE_SIZE_MAX)
    offset = _coerce_offset(offset)
    selected_types = _coerce_document_types(document_types)

    async with ctx.deps.open_tool_session() as session:
        conditions: list[Any] = []
        _apply_document_filters(
            conditions, document_types=selected_types, exclusion_filter=exclusion_filter
        )
        total_count = await session.scalar(
            select(func.count()).select_from(Document).where(*conditions)
        )
        documents = (
            (
                await session.execute(
                    select(Document)
                    .where(*conditions)
                    .order_by(Document.type.asc(), Document.title.asc(), Document.id_.asc())
                    .offset(offset)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )

    excluded_source_keys = await _excluded_source_keys(
        ctx, [document.source_key for document in documents], exclusion_filter
    )
    total = total_count or 0
    sections = [
        "# RAG document listing",
        _join_present(
            [
                f"document_types: {_document_types_label(selected_types)}",
                f"exclusion_filter: {exclusion_filter}",
                *_pagination_lines(
                    returned_count=len(documents),
                    total_count=total,
                    page_size=page_size,
                    offset=offset,
                ),
            ]
        ),
    ]
    sections.append(
        _document_table(
            [
                (offset + index, document, document.source_key in excluded_source_keys, None)
                for index, document in enumerate(documents, start=1)
            ]
        )
    )
    return "\n\n".join(sections)


async def search_rag_documents(
    ctx: RunContext[Deps],
    query: str,
    document_types: list[str] | None = None,
    page_size: int = 100,
    offset: int = 0,
    exclusion_filter: RagExclusionFilter = "included",
    search_mode: Literal["full_text", "exact"] = "full_text",
) -> str:
    """Search indexed RAG documents with assistant-controlled pagination.

    full_text mode uses PostgreSQL weighted search_vector and ts_rank_cd. exact mode uses
    case-insensitive substring matching over title, URL, school, and full Markdown.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    page_size = _coerce_bounded_positive(page_size, "page_size", max_value=_DOCUMENT_PAGE_SIZE_MAX)
    offset = _coerce_offset(offset)
    selected_types = _coerce_document_types(document_types)
    pattern = f"%{query}%"
    search_vector: ColumnElement[Any] = literal_column("document.search_vector")
    full_text_query = None

    async with ctx.deps.open_tool_session() as session:
        conditions: list[Any] = []
        if search_mode == "full_text":
            full_text_query = func.websearch_to_tsquery("simple", query)
            conditions.append(search_vector.op("@@")(full_text_query))
        elif search_mode == "exact":
            conditions.append(
                or_(
                    Document.title.ilike(pattern),
                    Document.url.ilike(pattern),
                    Document.school.ilike(pattern),
                    Document.markdown_content.ilike(pattern),
                )
            )
        else:
            raise ValueError('search_mode must be "full_text" or "exact"')
        _apply_document_filters(
            conditions, document_types=selected_types, exclusion_filter=exclusion_filter
        )
        total_count = await session.scalar(
            select(func.count()).select_from(Document).where(*conditions)
        )
        if full_text_query is not None:
            rank_expr = func.ts_rank_cd(search_vector, full_text_query)
            headline_expr = func.ts_headline(
                "simple", Document.markdown_content, full_text_query, _FULL_TEXT_HEADLINE_OPTIONS
            )
            rows = (
                await session.execute(
                    select(Document, rank_expr.label("rank"), headline_expr.label("headline"))
                    .where(*conditions)
                    .order_by(
                        desc(rank_expr),
                        Document.type.asc(),
                        Document.title.asc(),
                        Document.id_.asc(),
                    )
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()
            documents = [(document, rank, headline) for document, rank, headline in rows]
        else:
            rows = (
                (
                    await session.execute(
                        select(Document)
                        .where(*conditions)
                        .order_by(Document.type.asc(), Document.title.asc(), Document.id_.asc())
                        .offset(offset)
                        .limit(page_size)
                    )
                )
                .scalars()
                .all()
            )
            documents = [
                (document, None, _content_snippet(document.markdown_content, query))
                for document in rows
            ]

    excluded_source_keys = await _excluded_source_keys(
        ctx, [document.source_key for document, _rank, _headline in documents], exclusion_filter
    )
    total = total_count or 0
    sections = [
        "# RAG document search",
        _join_present(
            [
                f"query: {query}",
                f"search_mode: {search_mode}",
                f"document_types: {_document_types_label(selected_types)}",
                f"exclusion_filter: {exclusion_filter}",
                *_pagination_lines(
                    returned_count=len(documents),
                    total_count=total,
                    page_size=page_size,
                    offset=offset,
                ),
            ]
        ),
    ]
    sections.append(
        _document_table(
            [
                (
                    offset + index,
                    document,
                    document.source_key in excluded_source_keys,
                    f"{rank:.4g}" if rank is not None else None,
                )
                for index, (document, rank, _headline) in enumerate(documents, start=1)
            ],
            include_rank=search_mode == "full_text",
        )
    )
    snippet_sections: list[str] = []
    for index, (document, _rank, headline) in enumerate(documents, start=1):
        matched_fields = ", ".join(_matched_document_fields(document, query)) or "fts_only"
        snippet = _multiline_block("snippet", headline)
        if snippet is not None:
            snippet_sections.append(
                "\n".join(
                    [
                        f"## {offset + index}. {_document_ref(document)} snippet",
                        f"matched_fields: {matched_fields}",
                        snippet,
                    ]
                )
            )
    if snippet_sections:
        sections.append("\n\n".join(snippet_sections))
    return "\n\n".join(sections)


async def inspect_rag_document(
    ctx: RunContext[Deps],
    document_type: str,
    document_id: int,
    chunk_mode: Literal["none", "metadata", "content"] = "none",
) -> str:
    """Inspect one indexed RAG document by type/id with full stored Markdown content.

    chunk_mode defaults to none because full chunks duplicate the Markdown content; use metadata
    for chunk boundaries/counts or content for full chunk text.
    """
    selected_type = DocumentType(document_type)
    if chunk_mode not in {"none", "metadata", "content"}:
        raise ValueError('chunk_mode must be "none", "metadata", or "content"')

    async with ctx.deps.open_tool_session() as session:
        document = await session.scalar(
            select(Document).where(Document.type == selected_type, Document.id_ == document_id)
        )
        if document is None:
            raise ValueError(f"RAG document not found: {document_type}:{document_id}")
        chunks: list[DocumentContentChunk] = []
        if chunk_mode == "none":
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(DocumentContentChunk)
                .where(DocumentContentChunk.document_id == document.id)
            )
            chunks = []
        else:
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
            chunk_count = len(chunks)

    excluded_source_keys = await _excluded_source_keys(ctx, [document.source_key])
    sections = [
        f"# RAG document inspection: {_document_ref(document)} — {document.title}",
        _join_present(
            [
                *_document_metadata_lines(
                    document, excluded=document.source_key in excluded_source_keys
                ),
                f"chunk_count: {chunk_count or 0}",
            ]
        ),
        _multiline_block("content", document.markdown_content) or "",
    ]
    if chunk_mode != "none":
        chunk_sections = ["# Chunks"]
        for chunk in chunks:
            chunk_sections.append(
                _join_present(
                    [
                        f"## chunk {chunk.sequence_number}",
                        f"tokens: {chunk.token_count}; chars: {chunk.character_count}",
                        _multiline_block("chunk", chunk.content)
                        if chunk_mode == "content"
                        else None,
                    ]
                )
            )
        sections.append("\n\n".join(chunk_sections))
    return "\n\n".join(sections)
