from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentType, OtelSpan
from app.rag.training_materials.urls import training_material_demo_url_from_url

MessageSourceType = DocumentType | Literal["canned_response"]
MessageSourceUsage = Literal["search", "lookup", "retrieved_by_id", "prompt"]
GroundingSourceSelection = str | dict[str, Any]

CANNED_RESPONSE_SOURCE_TYPE: Literal["canned_response"] = "canned_response"
CANNED_RESPONSE_SOURCE_KEY = "prompt:canned_response:0:prompt:0"
CANNED_RESPONSE_SOURCE_TOOL_CALL_ID = "prompt"
CANNED_RESPONSE_SOURCE_TOOL_NAME = "canned_response"
CANNED_RESPONSE_SOURCE_TITLE = "Approved prompt guidance"
CANNED_RESPONSE_SOURCE_NOTE = (
    "Represents approved VA prompt canned wording or response policy rather than a "
    "retrieved document."
)

_MARKDOWN_SOURCE_TABLE_COLUMN_COUNT = 3
_ID_TITLE_ROW_MIN_COLUMN_COUNT = 2

_SEARCH_TOOL_NAMES = frozenset({"find_document_chunks", "find_document_titles"})
_RETRIEVE_BY_ID_TOOL_NAMES = frozenset({"retrieve_documents"})
_SOURCE_TOOL_NAMES = frozenset(
    {
        *_SEARCH_TOOL_NAMES,
        *_RETRIEVE_BY_ID_TOOL_NAMES,
        "list_catalog_pages",
        "list_catalog_programs",
        "list_catalog_programs_by_school",
        "list_catalog_courses",
        "list_catalog_courses_for_program",
        "list_website_pages",
        "list_website_programs",
    }
)
_FIND_DOCUMENT_CHUNKS_SCHEMA = "find_document_chunks.v2"
_FIND_DOCUMENT_CHUNKS_SCHEMA_ATTRIBUTE = "app.document_tool.find_document_chunks.schema"
_FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE = (
    "app.document_tool.find_document_chunks.full_provenance"
)


class MessageSourceUsed(BaseModel):
    key: str
    type: MessageSourceType
    id: int
    title: str
    url: str
    usage: MessageSourceUsage
    tool_call_id: str
    tool_name: str
    search_query: str | None = None
    chunk: str | None = None
    explanation: str | None = None


def message_source_type_value(source_type: MessageSourceType) -> str:
    if isinstance(source_type, DocumentType):
        return source_type.value
    return source_type


def grounding_selection_key(selection: GroundingSourceSelection) -> str | None:
    if isinstance(selection, str):
        return selection
    key = selection.get("key")
    return key if isinstance(key, str) and key.strip() != "" else None


def is_canned_response_source(source: MessageSourceUsed) -> bool:
    return message_source_type_value(source.type) == CANNED_RESPONSE_SOURCE_TYPE


def _canned_response_source_key(index: int) -> str:
    return f"prompt:canned_response:{index}:prompt:0"


def build_canned_response_source(
    *,
    index: int = 0,
    key: str | None = None,
    title: str | None = None,
    explanation: str | None = None,
) -> MessageSourceUsed:
    return MessageSourceUsed(
        key=key
        or (CANNED_RESPONSE_SOURCE_KEY if index == 0 else _canned_response_source_key(index)),
        type=CANNED_RESPONSE_SOURCE_TYPE,
        id=index,
        title=title or CANNED_RESPONSE_SOURCE_TITLE,
        url="",
        usage="prompt",
        tool_call_id=CANNED_RESPONSE_SOURCE_TOOL_CALL_ID,
        tool_name=CANNED_RESPONSE_SOURCE_TOOL_NAME,
        chunk=CANNED_RESPONSE_SOURCE_NOTE,
        explanation=explanation,
    )


def with_canned_response_source_candidate(
    sources: list[MessageSourceUsed],
) -> list[MessageSourceUsed]:
    if any(is_canned_response_source(source) for source in sources):
        return list(sources)
    return [*sources, build_canned_response_source()]


def _source_from_canned_response_selection(
    selection: dict[str, Any], *, fallback_index: int
) -> MessageSourceUsed | None:
    key = grounding_selection_key(selection)
    if selection.get("type") != CANNED_RESPONSE_SOURCE_TYPE and not (
        key is not None and key.startswith("prompt:canned_response:")
    ):
        return None

    raw_id = selection.get("id")
    index = raw_id if isinstance(raw_id, int) and raw_id >= 0 else fallback_index
    title = selection.get("title")
    explanation = selection.get("explanation")
    return build_canned_response_source(
        index=index,
        key=key,
        title=title if isinstance(title, str) and title.strip() else None,
        explanation=(explanation if isinstance(explanation, str) and explanation.strip() else None),
    )


def filter_sources_by_keys(
    sources: Sequence[MessageSourceUsed], selected_keys: Sequence[GroundingSourceSelection] | None
) -> list[MessageSourceUsed]:
    source_by_key = {source.key: source for source in sources}
    selected_sources: list[MessageSourceUsed] = []
    canned_selection_index = 0
    for selection in selected_keys or []:
        if isinstance(selection, str):
            source = source_by_key.get(selection)
            if source is not None:
                selected_sources.append(source)
            continue

        canned_source = _source_from_canned_response_selection(
            selection, fallback_index=canned_selection_index
        )
        if canned_source is not None:
            selected_sources.append(canned_source)
            canned_selection_index += 1
            continue

        key = grounding_selection_key(selection)
        if key is not None and key in source_by_key:
            selected_sources.append(source_by_key[key])
    return selected_sources


@dataclass(frozen=True)
class _SourceCandidate:
    type: DocumentType
    id: int
    usage: MessageSourceUsage
    title: str | None = None
    url: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    search_query: str | None = None
    chunk: str | None = None


def _parse_json_attribute(value: Any, *, span_id: str, attribute_name: str) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in source tool span {span_id} attribute {attribute_name}: {value}"
        ) from error


def _source_from_mapping(
    value: dict[str, Any], *, usage: MessageSourceUsage, include_chunk: bool, span_id: str
) -> _SourceCandidate | None:
    if "type" not in value and "id" not in value:
        return None

    raw_type = value.get("type")
    raw_id = value.get("id")
    if not isinstance(raw_type, str) or not isinstance(raw_id, int):
        raise TypeError(f"Malformed source in source tool span {span_id}: {value}")
    try:
        doc_type = DocumentType(raw_type)
    except ValueError as error:
        raise ValueError(
            f"Unknown source document type in source tool span {span_id}: {raw_type}"
        ) from error

    title = value.get("title")
    if title is not None and not isinstance(title, str):
        raise TypeError(f"Malformed source title in source tool span {span_id}: {value}")
    url = value.get("url")
    if url is not None and not isinstance(url, str):
        raise TypeError(f"Malformed source URL in source tool span {span_id}: {value}")
    content = value.get("content")
    if include_chunk and content is not None and not isinstance(content, str):
        raise TypeError(f"Malformed source chunk in source tool span {span_id}: {value}")

    return _SourceCandidate(
        type=doc_type,
        id=raw_id,
        usage=usage,
        title=title if isinstance(title, str) and title.strip() != "" else None,
        url=url if isinstance(url, str) and url.strip() != "" else None,
        chunk=content
        if include_chunk and isinstance(content, str) and content.strip() != ""
        else None,
    )


def _source_candidates_from_find_document_chunks_v2_sources(
    sources: Any, *, usage: MessageSourceUsage, span_id: str, chunk: str | None
) -> list[_SourceCandidate]:
    if not isinstance(sources, dict):
        raise TypeError(f"Malformed find_document_chunks.v2 sources in span {span_id}: {sources}")

    candidates: list[_SourceCandidate] = []
    source_mapping = cast(dict[object, object], sources)
    for raw_type, raw_rows in source_mapping.items():
        if not isinstance(raw_type, str):
            raise TypeError(
                f"Malformed find_document_chunks.v2 source type in span {span_id}: {raw_type}"
            )
        try:
            doc_type = DocumentType(raw_type)
        except ValueError as error:
            raise ValueError(
                f"Unknown find_document_chunks.v2 source document type in span "
                f"{span_id}: {raw_type}"
            ) from error
        if not isinstance(raw_rows, list):
            raise TypeError(
                f"Malformed find_document_chunks.v2 source rows in span {span_id}: {raw_rows}"
            )
        source_rows = cast(list[object], raw_rows)
        for raw_row in source_rows:
            if not isinstance(raw_row, list | tuple):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 source row in span {span_id}: {raw_row}"
                )
            row = cast(list[object] | tuple[object, ...], raw_row)
            if len(row) != 3:  # noqa: PLR2004
                raise TypeError(
                    f"Malformed find_document_chunks.v2 source row in span {span_id}: {raw_row}"
                )
            raw_id, raw_sequence_numbers, raw_title = row[0], row[1], row[2]
            if not isinstance(raw_id, int):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 source id in span {span_id}: {raw_row}"
                )
            if not isinstance(raw_sequence_numbers, list):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 sequence numbers in span {span_id}: "
                    f"{raw_row}"
                )
            sequence_numbers = cast(list[object], raw_sequence_numbers)
            if not all(isinstance(sequence_number, int) for sequence_number in sequence_numbers):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 sequence numbers in span {span_id}: "
                    f"{raw_row}"
                )
            if not isinstance(raw_title, str):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 source title in span {span_id}: {raw_row}"
                )
            candidates.append(
                _SourceCandidate(
                    type=doc_type,
                    id=raw_id,
                    usage=usage,
                    title=raw_title if raw_title.strip() != "" else None,
                    chunk=chunk if chunk is not None and chunk.strip() != "" else None,
                )
            )
    return candidates


def _find_document_chunks_v2_full_results_by_index(
    full_provenance: Any, *, span_id: str
) -> dict[int, dict[str, Any]]:
    if full_provenance is None:
        return {}
    parsed = _parse_json_attribute(
        full_provenance,
        span_id=span_id,
        attribute_name=_FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE,
    )
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise TypeError(
            f"Expected JSON object in source tool span {span_id} attribute "
            f"{_FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE}: {parsed}"
        )
    parsed_mapping = cast(dict[str, object], parsed)
    if parsed_mapping.get("schema") != _FIND_DOCUMENT_CHUNKS_SCHEMA:
        raise ValueError(
            f"Unknown find_document_chunks full provenance schema in span {span_id}: "
            f"{parsed_mapping.get('schema')}"
        )
    results = parsed_mapping.get("results")
    if not isinstance(results, list):
        raise TypeError(
            f"Malformed find_document_chunks full provenance results in span {span_id}: {parsed}"
        )

    by_index: dict[int, dict[str, Any]] = {}
    result_items = cast(list[object], results)
    for item in result_items:
        if not isinstance(item, dict):
            raise TypeError(
                f"Malformed find_document_chunks full provenance item in span {span_id}: {item}"
            )
        item_mapping = cast(dict[str, object], item)
        result_index = item_mapping.get("result_index")
        if not isinstance(result_index, int):
            raise TypeError(
                f"Malformed find_document_chunks full provenance result_index in span "
                f"{span_id}: {item}"
            )
        by_index[result_index] = cast(dict[str, Any], item_mapping)
    return by_index


def _source_candidates_from_find_document_chunks_v2_results(
    result_items: list[object],
    *,
    full_provenance: Any,
    usage: MessageSourceUsage,
    search_query: str | None,
    span_id: str,
) -> list[_SourceCandidate]:
    full_results_by_index = _find_document_chunks_v2_full_results_by_index(
        full_provenance, span_id=span_id
    )
    candidates: list[_SourceCandidate] = []
    pending_search_query = search_query
    for index, raw_result in enumerate(result_items):
        if not isinstance(raw_result, dict):
            raise TypeError(
                f"Malformed find_document_chunks.v2 result item in span {span_id}: {raw_result}"
            )
        result_item = cast(dict[str, object], raw_result)
        content = result_item.get("content")
        if not isinstance(content, str):
            raise TypeError(
                f"Malformed find_document_chunks.v2 result content in span {span_id}: {raw_result}"
            )
        inline_sources = result_item.get("sources")
        if not isinstance(inline_sources, dict):
            raise TypeError(
                f"Malformed find_document_chunks.v2 result sources in span {span_id}: {raw_result}"
            )
        provenance_item = full_results_by_index.get(index, result_item)
        sources = provenance_item.get("sources")
        item_candidates = _source_candidates_from_find_document_chunks_v2_sources(
            sources, usage=usage, span_id=span_id, chunk=content
        )
        for candidate in item_candidates:
            candidates.append(replace(candidate, search_query=pending_search_query))
            pending_search_query = None
    return candidates


def _find_document_chunks_schema(attributes: dict[str, Any], *, span_id: str) -> str | None:
    raw_schema = attributes.get(_FIND_DOCUMENT_CHUNKS_SCHEMA_ATTRIBUTE)
    if raw_schema is None:
        return None
    if not isinstance(raw_schema, str):
        raise TypeError(
            f"Malformed find_document_chunks schema in source tool span {span_id}: {raw_schema}"
        )
    schema = raw_schema.strip()
    if schema == "":
        raise ValueError(f"Blank find_document_chunks schema in source tool span {span_id}")
    if schema != _FIND_DOCUMENT_CHUNKS_SCHEMA:
        raise ValueError(
            f"Unknown find_document_chunks schema in source tool span {span_id}: {schema}"
        )
    return schema


def _split_markdown_table_cells(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|")
    body = body.removesuffix("|")

    cells: list[str] = []
    current_cell: list[str] = []
    index = 0
    while index < len(body):
        character = body[index]
        if character == "\\" and index + 1 < len(body) and body[index + 1] in {"\\", "|"}:
            current_cell.append(body[index + 1])
            index += 2
            continue
        if character == "|":
            cells.append("".join(current_cell).strip())
            current_cell = []
            index += 1
            continue
        current_cell.append(character)
        index += 1
    cells.append("".join(current_cell).strip())
    return cells


def _source_candidates_from_markdown_table(
    value: str, *, usage: MessageSourceUsage, search_query: str | None = None
) -> list[_SourceCandidate]:
    candidates: list[_SourceCandidate] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = _split_markdown_table_cells(stripped)
        if len(cells) != _MARKDOWN_SOURCE_TABLE_COLUMN_COUNT:
            raise ValueError(f"Malformed source Markdown table row: {stripped}")
        if cells[0].lower() == "id":
            continue
        raw_id, raw_type, title = cells
        try:
            doc_id = int(raw_id)
        except ValueError as error:
            raise ValueError(f"Malformed source ID in Markdown table row: {stripped}") from error
        try:
            doc_type = DocumentType(raw_type)
        except ValueError as error:
            raise ValueError(
                f"Unknown source document type in Markdown table row: {stripped}"
            ) from error
        if title == "":
            raise ValueError(f"Malformed source title in Markdown table row: {stripped}")
        candidates.append(
            _SourceCandidate(
                type=doc_type, id=doc_id, usage=usage, title=title, search_query=search_query
            )
        )
        search_query = None
    return candidates


def _source_candidates_from_id_title_list(
    value: Any, *, doc_type: DocumentType, usage: MessageSourceUsage, span_id: str
) -> list[_SourceCandidate]:
    parsed = _parse_json_attribute(value, span_id=span_id, attribute_name="gen_ai.tool.call.result")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise TypeError(
            f"Expected JSON array in source tool span {span_id} "
            f"attribute gen_ai.tool.call.result: {parsed}"
        )
    candidates: list[_SourceCandidate] = []
    rows = cast(list[Any], parsed)
    for item in rows:
        if not isinstance(item, list | tuple):
            raise TypeError(
                f"Malformed {doc_type.value} ID/title source row in source tool span "
                f"{span_id}: {item}"
            )
        row = cast(tuple[Any, ...] | list[Any], item)
        if len(row) < _ID_TITLE_ROW_MIN_COLUMN_COUNT:
            raise ValueError(
                f"Malformed {doc_type.value} ID/title source row in source tool span "
                f"{span_id}: {item}"
            )
        raw_id, raw_title = row[0], row[1]
        if not isinstance(raw_id, int) or not isinstance(raw_title, str):
            raise TypeError(
                f"Malformed {doc_type.value} ID/title source row in source tool span "
                f"{span_id}: {item}"
            )
        if raw_title.strip() == "":
            raise ValueError(
                f"Malformed {doc_type.value} ID/title source row in source tool span "
                f"{span_id}: {item}"
            )
        candidates.append(_SourceCandidate(type=doc_type, id=raw_id, usage=usage, title=raw_title))
    return candidates


def _collect_sources_from_tool_result(
    value: Any,
    *,
    span_id: str,
    tool_name: str,
    usage: MessageSourceUsage,
    search_query: str | None = None,
    include_chunks: bool = False,
) -> list[_SourceCandidate]:
    if tool_name == "find_document_titles" and isinstance(value, str):
        return _source_candidates_from_markdown_table(value, usage=usage, search_query=search_query)
    if tool_name == "list_website_pages":
        return _source_candidates_from_id_title_list(
            value, doc_type=DocumentType.WEBSITE_PAGE, usage=usage, span_id=span_id
        )
    if tool_name == "list_website_programs":
        return _source_candidates_from_id_title_list(
            value, doc_type=DocumentType.WEBSITE_PROGRAM, usage=usage, span_id=span_id
        )
    parsed = _parse_json_attribute(value, span_id=span_id, attribute_name="gen_ai.tool.call.result")
    if parsed is None:
        return []
    if not isinstance(parsed, list | dict):
        raise TypeError(
            f"Expected JSON object or array in source tool span {span_id} "
            f"attribute gen_ai.tool.call.result: {parsed}"
        )
    candidates: list[_SourceCandidate] = []
    pending_search_query = search_query

    def visit(item: Any) -> None:
        nonlocal pending_search_query
        if isinstance(item, list):
            for child in cast(list[Any], item):
                visit(child)
            return
        if not isinstance(item, dict):
            return

        mapping = cast(dict[str, Any], item)
        candidate = _source_from_mapping(
            mapping, usage=usage, include_chunk=include_chunks, span_id=span_id
        )
        if candidate is not None:
            candidates.append(replace(candidate, search_query=pending_search_query))
            pending_search_query = None

        # Some catalog helper tools return nested shapes, e.g. a program plus courses.
        for nested_key in ("program", "courses"):
            nested = mapping.get(nested_key)
            if nested is not None:
                visit(nested)

    visit(parsed)
    return candidates


def _normalize_url(doc_type: DocumentType, url: str) -> str:
    if doc_type == DocumentType.TRAINING_MATERIAL and url.startswith("training-materials://"):
        return training_material_demo_url_from_url(url)
    return url


def _usage_for_tool(tool_name: str) -> MessageSourceUsage:
    if tool_name in _RETRIEVE_BY_ID_TOOL_NAMES:
        return "retrieved_by_id"
    if tool_name in _SEARCH_TOOL_NAMES:
        return "search"
    return "lookup"


def _search_query_from_tool_arguments(
    tool_name: str, arguments: Any, *, span_id: str
) -> str | None:
    if tool_name not in _SEARCH_TOOL_NAMES:
        return None
    parsed = _parse_json_attribute(
        arguments, span_id=span_id, attribute_name="gen_ai.tool.call.arguments"
    )
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise TypeError(
            f"Expected JSON object in source tool span {span_id} "
            f"attribute gen_ai.tool.call.arguments: {parsed}"
        )
    mapping = cast(dict[str, Any], parsed)
    query_keys = ("content_search_query", "title_search_query", "query")
    for key in query_keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return None


def _source_candidates_from_tool_span(
    *, span_id: str, attributes: dict[str, Any]
) -> list[_SourceCandidate]:
    tool_name = attributes.get("gen_ai.tool.name")
    if not isinstance(tool_name, str) or tool_name not in _SOURCE_TOOL_NAMES:
        return []
    if "gen_ai.tool.call.result" not in attributes:
        return []

    usage = _usage_for_tool(tool_name)
    search_query = _search_query_from_tool_arguments(
        tool_name, attributes.get("gen_ai.tool.call.arguments"), span_id=span_id
    )
    raw_result = attributes["gen_ai.tool.call.result"]
    if tool_name == "find_document_chunks":
        parsed_result = _parse_json_attribute(
            raw_result, span_id=span_id, attribute_name="gen_ai.tool.call.result"
        )
        schema = _find_document_chunks_schema(attributes, span_id=span_id)
        if schema == _FIND_DOCUMENT_CHUNKS_SCHEMA:
            if not isinstance(parsed_result, list):
                raise TypeError(
                    f"Malformed find_document_chunks.v2 result array in span "
                    f"{span_id}: {parsed_result}"
                )
            candidates = _source_candidates_from_find_document_chunks_v2_results(
                cast(list[object], parsed_result),
                full_provenance=attributes.get(_FIND_DOCUMENT_CHUNKS_FULL_PROVENANCE_ATTRIBUTE),
                usage=usage,
                search_query=search_query,
                span_id=span_id,
            )
        else:
            candidates = _collect_sources_from_tool_result(
                parsed_result,
                span_id=span_id,
                tool_name=tool_name,
                usage=usage,
                search_query=search_query,
                include_chunks=True,
            )
    else:
        candidates = _collect_sources_from_tool_result(
            raw_result,
            span_id=span_id,
            tool_name=tool_name,
            usage=usage,
            search_query=search_query,
            include_chunks=False,
        )
    return [
        replace(candidate, tool_call_id=span_id, tool_name=tool_name) for candidate in candidates
    ]


async def _document_lookup_for_candidates(
    session: AsyncSession, candidates_by_message_id: dict[UUID, list[_SourceCandidate]]
) -> dict[tuple[DocumentType, int], tuple[str, str]]:
    criteria_by_type: dict[DocumentType, set[int]] = {}
    for candidates in candidates_by_message_id.values():
        for candidate in candidates:
            if candidate.title is None or candidate.url is None:
                criteria_by_type.setdefault(candidate.type, set()).add(candidate.id)

    db_lookup: dict[tuple[DocumentType, int], tuple[str, str]] = {}
    for doc_type, ids in criteria_by_type.items():
        rows = (
            await session.execute(
                select(Document.type, Document.id_, Document.title, Document.url).where(
                    Document.type == doc_type, Document.id_.in_(ids)
                )
            )
        ).all()
        for row in rows:
            db_lookup[(row.type, row.id_)] = (row.title, row.url)
    return db_lookup


def _message_sources_from_candidates(
    candidates: list[_SourceCandidate], db_lookup: dict[tuple[DocumentType, int], tuple[str, str]]
) -> list[MessageSourceUsed]:
    sources: list[MessageSourceUsed] = []
    key_occurrences: dict[str, int] = {}
    for candidate in candidates:
        if candidate.tool_call_id is None or candidate.tool_name is None:
            raise ValueError(f"Source candidate is missing tool context: {candidate}")
        key_base = (
            f"{candidate.tool_call_id}:{candidate.type.value}:{candidate.id}:{candidate.usage}"
        )
        occurrence = key_occurrences.get(key_base, 0)
        key_occurrences[key_base] = occurrence + 1

        db_title, db_url = db_lookup.get((candidate.type, candidate.id), (None, None))
        title = candidate.title or db_title
        url = candidate.url or db_url
        if title is None or url is None:
            # Historical traces can outlive RAG document rows after rebuilds/deletions.
            # Missing DB resolution is not malformed trace JSON, so omit that stale source
            # instead of failing the whole conversation detail or final stream payload.
            continue
        sources.append(
            MessageSourceUsed(
                key=f"{key_base}:{occurrence}",
                type=candidate.type,
                id=candidate.id,
                title=title,
                url=_normalize_url(candidate.type, url),
                usage=candidate.usage,
                tool_call_id=candidate.tool_call_id,
                tool_name=candidate.tool_name,
                search_query=candidate.search_query,
                chunk=candidate.chunk,
            )
        )
    return sources


async def get_tool_sources_used_for_message(
    session: AsyncSession, message_id: UUID
) -> list[MessageSourceUsed]:
    return (await get_tool_sources_used_by_message_ids(session, [message_id])).get(message_id, [])


async def get_tool_sources_used_by_message_ids(
    session: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[MessageSourceUsed]]:
    if not message_ids:
        return {}

    trace_rows = (
        await session.execute(
            select(OtelSpan.message_id, OtelSpan.trace_id)
            .where(OtelSpan.message_id.in_(message_ids))
            .where(OtelSpan.trace_id.is_not(None))
            .distinct()
        )
    ).all()
    trace_to_message_id = {
        trace_id: message_id
        for message_id, trace_id in trace_rows
        if message_id is not None and trace_id is not None
    }
    if not trace_to_message_id:
        return {}

    trace_ids = list(trace_to_message_id)
    span_rows = (
        await session.execute(
            select(OtelSpan.trace_id, OtelSpan.span_id, OtelSpan.attributes)
            .where(OtelSpan.trace_id.in_(trace_ids))
            .order_by(OtelSpan.start_time.asc().nullslast(), OtelSpan.created_at.asc())
        )
    ).all()

    candidates_by_message_id: dict[UUID, list[_SourceCandidate]] = {}
    for trace_id, span_id, attributes in span_rows:
        message_id = trace_to_message_id.get(trace_id)
        if message_id is None or not attributes:
            continue
        candidates = _source_candidates_from_tool_span(span_id=span_id, attributes=attributes)
        if candidates:
            candidates_by_message_id.setdefault(message_id, []).extend(candidates)

    if not candidates_by_message_id:
        return {}

    db_lookup = await _document_lookup_for_candidates(session, candidates_by_message_id)
    result: dict[UUID, list[MessageSourceUsed]] = {}
    for message_id, candidates in candidates_by_message_id.items():
        sources = _message_sources_from_candidates(candidates, db_lookup)
        if sources:
            result[message_id] = sources
    return result
