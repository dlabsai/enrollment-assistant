from __future__ import annotations

import json
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from pydantic_ai import RunContext

    from app.chat.tools.deps import Deps

from app.chat.tools import document
from app.chat.tools.models import (
    Document,
    DocumentChunkResult,
    DocumentTitleResult,
    FindDocumentChunksDedupeSummary,
    FindDocumentChunksResultItem,
    TruncatedDocInfo,
)
from app.models import DocumentType


class FakeSpan:
    def __init__(self, name: str, attributes: dict[str, object] | None = None) -> None:
        self.name = name
        self.attributes: dict[str, object] = dict(attributes or {})

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


@contextmanager
def fake_tool_span_factory(spans: list[FakeSpan]) -> Generator[object]:
    @contextmanager
    def fake_tool_span(name: str, *, tool_type: str) -> Generator[FakeSpan]:
        span = FakeSpan(
            f"execute_tool {name}",
            {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": name,
                "gen_ai.tool.type": tool_type,
            },
        )
        spans.append(span)
        yield span

    yield fake_tool_span


@contextmanager
def fake_retrieval_span_factory(spans: list[FakeSpan]) -> Generator[object]:
    @contextmanager
    def fake_retrieval_span(
        *, data_source_id: str, query: str, top_k: int | None
    ) -> Generator[FakeSpan]:
        attributes: dict[str, object] = {
            "gen_ai.operation.name": "retrieval",
            "gen_ai.data_source.id": data_source_id,
            "gen_ai.retrieval.query.text": query,
        }
        if top_k is not None:
            attributes["gen_ai.request.top_k"] = top_k
        span = FakeSpan(f"retrieval {data_source_id}", attributes)
        spans.append(span)
        yield span

    yield fake_retrieval_span


def _patch_span_factories(monkeypatch: pytest.MonkeyPatch, spans: list[FakeSpan]) -> None:
    with fake_tool_span_factory(spans) as fake_tool_span:
        monkeypatch.setattr(document, "start_genai_tool_span", fake_tool_span)
    with fake_retrieval_span_factory(spans) as fake_retrieval_span:
        monkeypatch.setattr(document, "start_genai_retrieval_span", fake_retrieval_span)


def _ctx() -> RunContext[Deps]:
    @asynccontextmanager
    async def open_tool_session() -> AsyncGenerator[object]:
        yield object()

    return cast(
        "RunContext[Deps]",
        SimpleNamespace(
            deps=SimpleNamespace(
                is_internal=True, openai=object(), open_tool_session=open_tool_session
            )
        ),
    )


def _assert_no_legacy_app_chat_tool_attributes(attributes: dict[str, object]) -> None:
    assert all(not key.startswith("app.chat.tool.") for key in attributes)


def _assert_document_tool_span(span: FakeSpan, *, name: str, arguments: dict[str, object]) -> None:
    assert span.name == f"execute_tool {name}"
    assert span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert span.attributes["gen_ai.tool.name"] == name
    assert span.attributes["gen_ai.tool.type"] == "datastore"
    assert json.loads(str(span.attributes["gen_ai.tool.call.arguments"])) == arguments
    _assert_no_legacy_app_chat_tool_attributes(span.attributes)


@pytest.mark.asyncio
async def test_find_document_chunks_adds_full_gen_ai_tool_result_and_retrieval_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "chunk content " * 400
    representative_results = [
        DocumentChunkResult(
            type=DocumentType.WEBSITE_PAGE,
            id=101,
            title="Admissions",
            sequence_number=3,
            content=content,
        )
    ]
    result = [
        FindDocumentChunksResultItem(
            content=content, sources={"website_page": [(101, [3], "Admissions")]}
        )
    ]
    dedupe = FindDocumentChunksDedupeSummary(
        effective_limit=50,
        candidate_count=1,
        unique_candidates=1,
        unique_results=1,
        candidate_collapsed_occurrences=0,
        returned_collapsed_occurrences=0,
        omitted_candidate_collapsed_occurrences=0,
    )

    async def fake_find_document_chunks_db(*_: object, **__: object) -> object:
        return SimpleNamespace(
            result=result,
            dedupe=dedupe,
            full_provenance={
                "schema": "find_document_chunks.v2",
                "results": [
                    {
                        "result_index": 0,
                        "content_hash": "hash",
                        "sources": {"website_page": [(101, [3], "Admissions")]},
                        "occurrences": 1,
                        "source_documents": 1,
                    }
                ],
            },
            representative_results=representative_results,
        )

    spans: list[FakeSpan] = []
    _patch_span_factories(monkeypatch, spans)
    monkeypatch.setattr(document, "_find_document_chunks_db", fake_find_document_chunks_db)
    returned = await document.find_document_chunks(_ctx(), content_search_query="financial aid")

    assert returned == result
    tool_span, retrieval_span = spans
    _assert_document_tool_span(
        tool_span, name="find_document_chunks", arguments={"content_search_query": "financial aid"}
    )
    result_payload = json.loads(str(tool_span.attributes["gen_ai.tool.call.result"]))
    assert result_payload == [item.model_dump(mode="json") for item in result]
    assert result_payload[0] == {
        "content": content,
        "sources": {"website_page": [[101, [3], "Admissions"]]},
    }
    assert tool_span.attributes["app.document_tool.find_document_chunks.schema"] == (
        "find_document_chunks.v2"
    )
    assert json.loads(
        str(tool_span.attributes["app.document_tool.find_document_chunks.dedupe"])
    ) == dedupe.model_dump(mode="json")
    assert json.loads(
        str(tool_span.attributes["app.document_tool.find_document_chunks.full_provenance"])
    ) == {
        "schema": "find_document_chunks.v2",
        "results": [
            {
                "result_index": 0,
                "content_hash": "hash",
                "sources": {"website_page": [[101, [3], "Admissions"]]},
                "occurrences": 1,
                "source_documents": 1,
            }
        ],
    }

    assert retrieval_span.name == "retrieval demo-rag"
    assert retrieval_span.attributes["gen_ai.operation.name"] == "retrieval"
    assert retrieval_span.attributes["gen_ai.data_source.id"] == "demo-rag"
    assert retrieval_span.attributes["gen_ai.retrieval.query.text"] == "financial aid"
    assert retrieval_span.attributes["gen_ai.request.top_k"] == 50
    assert json.loads(str(retrieval_span.attributes["gen_ai.retrieval.documents"])) == [
        {"id": "website_page:101:chunk:3"}
    ]


def test_find_document_chunks_payload_groups_exact_content_and_caps_inline_sources() -> None:
    chunk_candidate = document._DocumentChunkCandidate  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    payload = document._build_find_document_chunks_payload(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [
            chunk_candidate(
                content="same chunk",
                sequence_number=5,
                document_type=DocumentType.WEBSITE_PAGE,
                document_id=101,
                title="Admissions",
            ),
            chunk_candidate(
                content="same chunk",
                sequence_number=3,
                document_type=DocumentType.WEBSITE_PAGE,
                document_id=101,
                title="Admissions",
            ),
            chunk_candidate(
                content="same chunk",
                sequence_number=2,
                document_type=DocumentType.TRAINING_MATERIAL,
                document_id=202,
                title="Admissions Guide",
            ),
            chunk_candidate(
                content="unique chunk",
                sequence_number=1,
                document_type=DocumentType.WEBSITE_PROGRAM,
                document_id=303,
                title="MBA",
            ),
        ],
        effective_limit=50,
        inline_source_limit=1,
    )

    result = [item.model_dump(mode="json") for item in payload.result]

    assert payload.dedupe.model_dump(mode="json") == {
        "effective_limit": 50,
        "candidate_count": 4,
        "unique_candidates": 2,
        "unique_results": 2,
        "candidate_collapsed_occurrences": 2,
        "returned_collapsed_occurrences": 2,
        "omitted_candidate_collapsed_occurrences": 0,
    }
    assert result[0] == {
        "content": "same chunk",
        "sources": {"website_page": [[101, [3, 5], "Admissions"]]},
    }
    assert result[1]["content"] == "unique chunk"
    assert payload.full_provenance["results"][0]["sources"] == {
        "website_page": [(101, [3, 5], "Admissions")],
        "training_material": [(202, [2], "Admissions Guide")],
    }
    assert payload.representative_results[0] == DocumentChunkResult(
        type=DocumentType.WEBSITE_PAGE,
        id=101,
        title="Admissions",
        sequence_number=5,
        content="same chunk",
    )


@pytest.mark.asyncio
async def test_find_document_chunks_sets_arguments_before_failed_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_find_document_chunks_db(*_: object, **__: object) -> list[DocumentChunkResult]:
        raise RuntimeError("embedding failed")

    spans: list[FakeSpan] = []
    _patch_span_factories(monkeypatch, spans)
    monkeypatch.setattr(document, "_find_document_chunks_db", fake_find_document_chunks_db)

    with pytest.raises(RuntimeError, match="embedding failed"):
        await document.find_document_chunks(_ctx(), content_search_query="financial aid")

    tool_span = spans[0]
    _assert_document_tool_span(
        tool_span, name="find_document_chunks", arguments={"content_search_query": "financial aid"}
    )
    assert "gen_ai.tool.call.result" not in tool_span.attributes


@pytest.mark.asyncio
async def test_find_document_chunks_records_document_type_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_kwargs: dict[str, object] = {}

    async def fake_find_document_chunks_db(*_: object, **kwargs: object) -> object:
        received_kwargs.update(kwargs)
        return SimpleNamespace(
            result=[],
            dedupe=FindDocumentChunksDedupeSummary(
                effective_limit=50,
                candidate_count=0,
                unique_candidates=0,
                unique_results=0,
                candidate_collapsed_occurrences=0,
                returned_collapsed_occurrences=0,
                omitted_candidate_collapsed_occurrences=0,
            ),
            full_provenance={"schema": "find_document_chunks.v2", "results": []},
            representative_results=[],
        )

    spans: list[FakeSpan] = []
    _patch_span_factories(monkeypatch, spans)
    monkeypatch.setattr(document, "_find_document_chunks_db", fake_find_document_chunks_db)
    await document.find_document_chunks_internal(
        _ctx(), content_search_query="payment plan", document_types=[DocumentType.TRAINING_MATERIAL]
    )

    tool_span = spans[0]
    _assert_document_tool_span(
        tool_span,
        name="find_document_chunks",
        arguments={"content_search_query": "payment plan", "document_types": ["training_material"]},
    )
    assert received_kwargs["document_types"] == [DocumentType.TRAINING_MATERIAL]


def test_format_document_title_results_supports_training_material_paths() -> None:
    result = document._format_document_title_results(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [
            DocumentTitleResult(
                type=DocumentType.TRAINING_MATERIAL,
                id=-135932535,
                title="Grad Admissions Online/02-Degree Program Resources/MBA.pdf",
            )
        ]
    )

    assert result == (
        "| id | type | title |\n"
        "|---:|---|---|\n"
        "| -135932535 | training_material | "
        "Grad Admissions Online/02-Degree Program Resources/MBA.pdf |"
    )


@pytest.mark.asyncio
async def test_find_document_titles_adds_full_gen_ai_tool_result_and_retrieval_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        DocumentTitleResult(type=DocumentType.WEBSITE_PROGRAM, id=22, title="MBA"),
        DocumentTitleResult(type=DocumentType.WEBSITE_PAGE, id=23, title="Tuition"),
    ]

    async def fake_find_document_titles_db(*_: object, **__: object) -> list[DocumentTitleResult]:
        return results

    spans: list[FakeSpan] = []
    _patch_span_factories(monkeypatch, spans)
    monkeypatch.setattr(document, "_find_document_titles_db", fake_find_document_titles_db)
    returned = await document.find_document_titles(_ctx(), title_search_query="business")

    assert returned == (
        "| id | type | title |\n"
        "|---:|---|---|\n"
        "| 22 | website_program | MBA |\n"
        "| 23 | website_page | Tuition |"
    )
    tool_span, retrieval_span = spans
    _assert_document_tool_span(
        tool_span, name="find_document_titles", arguments={"title_search_query": "business"}
    )
    assert tool_span.attributes["gen_ai.tool.call.result"] == (
        "| id | type | title |\n"
        "|---:|---|---|\n"
        "| 22 | website_program | MBA |\n"
        "| 23 | website_page | Tuition |"
    )
    assert retrieval_span.name == "retrieval demo-rag"
    assert retrieval_span.attributes["gen_ai.operation.name"] == "retrieval"
    assert retrieval_span.attributes["gen_ai.data_source.id"] == "demo-rag"
    assert retrieval_span.attributes["gen_ai.retrieval.query.text"] == "business"
    assert retrieval_span.attributes["gen_ai.request.top_k"] == 100
    assert json.loads(str(retrieval_span.attributes["gen_ai.retrieval.documents"])) == [
        {"id": "website_program:22"},
        {"id": "website_page:23"},
    ]


@pytest.mark.asyncio
async def test_retrieve_documents_adds_full_gen_ai_tool_result_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "document body " * 500
    documents = [
        Document(
            type=DocumentType.WEBSITE_PAGE,
            id=9,
            title="Transfer Credits",
            url="https://demo-university.example.edu/transfer-credits/",
            content=content,
        )
    ]
    truncated_info = TruncatedDocInfo(
        truncated_docs=[(DocumentType.WEBSITE_PAGE, 9, "Transfer Credits")]
    )

    async def fake_retrieve_documents_db(
        *_: object, **__: object
    ) -> tuple[list[Document], None, TruncatedDocInfo]:
        return documents, None, truncated_info

    spans: list[FakeSpan] = []
    _patch_span_factories(monkeypatch, spans)
    monkeypatch.setattr(document, "_retrieve_documents_db", fake_retrieve_documents_db)
    returned = await document.retrieve_documents(
        _ctx(), website_page_ids=[9], catalog_page_ids=[10]
    )
    returned_documents, not_found_ids, returned_truncated_info = returned

    assert returned_documents == documents
    assert not_found_ids is None
    assert returned_truncated_info == truncated_info
    span = spans[0]
    _assert_document_tool_span(
        span,
        name="retrieve_documents",
        arguments={
            "website_page_ids": [9],
            "website_program_ids": None,
            "catalog_page_ids": [10],
            "catalog_program_ids": None,
            "catalog_course_ids": None,
        },
    )
    result_payload = json.loads(str(span.attributes["gen_ai.tool.call.result"]))
    assert result_payload == [documents[0].model_dump(mode="json")]
    assert result_payload[0]["content"] == content
    assert json.loads(str(span.attributes["app.document_tool.truncated_info"])) == json.loads(
        truncated_info.model_dump_json()
    )
    _assert_no_legacy_app_chat_tool_attributes(span.attributes)
