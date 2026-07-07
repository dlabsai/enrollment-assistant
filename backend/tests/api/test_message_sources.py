from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.message_sources import get_tool_sources_used_by_message_ids
from app.models import Document, DocumentType, OtelSpan
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.rag.source_keys import document_source_key
from app.rag.training_materials.urls import training_material_demo_url_from_url


@pytest.mark.asyncio
async def test_markdown_table_sources_allow_escaped_pipes_in_titles(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        Document(
            type=DocumentType.WEBSITE_PROGRAM,
            id_=920022,
            source_key=document_source_key(
                DocumentType.WEBSITE_PROGRAM,
                920022,
                "MBA | Online",
                "https://demo-university.example.edu/program/mba-online",
                "MBA content",
            ),
            title="MBA | Online",
            url="https://demo-university.example.edu/program/mba-online",
            markdown_content="MBA content",
            token_count=2,
            character_count=11,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    transactional_session.add(
        OtelSpan(
            trace_id="trace-title-search",
            span_id="tool-title-search",
            message_id=message_id,
            name="execute_tool find_document_titles",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "find_document_titles",
                "gen_ai.tool.call.arguments": {"title_search_query": "business programs"},
                "gen_ai.tool.call.result": (
                    "| id | type | title |\n"
                    "|---:|---|---|\n"
                    "| 920022 | website_program | MBA \\| Online |"
                ),
            },
        )
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [message_id]
    )

    assert [source.title for source in sources_by_message_id[message_id]] == ["MBA | Online"]
    assert (
        sources_by_message_id[message_id][0].key
        == "tool-title-search:website_program:920022:search:0"
    )
    assert (
        sources_by_message_id[message_id][0].url
        == "https://demo-university.example.edu/program/mba-online"
    )
    assert sources_by_message_id[message_id][0].search_query == "business programs"


@pytest.mark.asyncio
async def test_tool_source_keys_do_not_depend_on_db_title_or_url(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    document = Document(
        type=DocumentType.WEBSITE_PAGE,
        id_=42,
        source_key=document_source_key(
            DocumentType.WEBSITE_PAGE,
            42,
            "Original Title",
            "https://demo-university.example.edu/original",
            "Original content",
        ),
        title="Original Title",
        url="https://demo-university.example.edu/original",
        markdown_content="Original content",
        token_count=2,
        character_count=16,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    transactional_session.add(document)
    transactional_session.add(
        OtelSpan(
            trace_id="trace-stable-source-key",
            span_id="tool-stable-source-key",
            message_id=message_id,
            name="execute_tool find_document_chunks",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "find_document_chunks",
                "gen_ai.tool.call.arguments": {"content_search_query": "source key"},
                "gen_ai.tool.call.result": [
                    {
                        "type": "website_page",
                        "id": 42,
                        "title": "Original Title",
                        "content": "Original chunk",
                    }
                ],
            },
        )
    )
    await transactional_session.flush()

    before = await get_tool_sources_used_by_message_ids(transactional_session, [message_id])
    document.title = "Updated Title"
    document.url = "https://demo-university.example.edu/updated"
    await transactional_session.flush()
    after = await get_tool_sources_used_by_message_ids(transactional_session, [message_id])

    assert before[message_id][0].key == after[message_id][0].key
    assert after[message_id][0].title == "Original Title"
    assert after[message_id][0].url == "https://demo-university.example.edu/updated"


@pytest.mark.asyncio
async def test_find_document_chunks_v2_projects_full_provenance_sources(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    documents = [
        Document(
            type=DocumentType.WEBSITE_PAGE,
            id_=101,
            source_key=document_source_key(
                DocumentType.WEBSITE_PAGE,
                101,
                "Admissions",
                "https://demo-university.example.edu/admissions",
                "Admissions content",
            ),
            title="Admissions DB Title",
            url="https://demo-university.example.edu/admissions-updated",
            markdown_content="Admissions content",
            token_count=2,
            character_count=18,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        ),
        Document(
            type=DocumentType.WEBSITE_PAGE,
            id_=102,
            source_key=document_source_key(
                DocumentType.WEBSITE_PAGE,
                102,
                "Tuition",
                "https://demo-university.example.edu/tuition",
                "Tuition content",
            ),
            title="Tuition DB Title",
            url="https://demo-university.example.edu/tuition",
            markdown_content="Tuition content",
            token_count=2,
            character_count=15,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        ),
        Document(
            type=DocumentType.WEBSITE_PROGRAM,
            id_=201,
            source_key=document_source_key(
                DocumentType.WEBSITE_PROGRAM,
                201,
                "MBA",
                "https://demo-university.example.edu/program/mba",
                "MBA content",
            ),
            title="MBA DB Title",
            url="https://demo-university.example.edu/program/mba",
            markdown_content="MBA content",
            token_count=2,
            character_count=11,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        ),
    ]
    transactional_session.add_all(documents)
    transactional_session.add(
        OtelSpan(
            trace_id="trace-chunks-v2",
            span_id="tool-chunks-v2",
            message_id=message_id,
            name="execute_tool find_document_chunks",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "find_document_chunks",
                "gen_ai.tool.call.arguments": {"content_search_query": "tuition"},
                "app.document_tool.find_document_chunks.schema": "find_document_chunks.v2",
                "gen_ai.tool.call.result": [
                    {
                        "content": "same chunk",
                        "sources": {"website_page": [[101, [3], "Admissions Trace Title"]]},
                    }
                ],
                "app.document_tool.find_document_chunks.full_provenance": json.dumps(
                    {
                        "schema": "find_document_chunks.v2",
                        "results": [
                            {
                                "result_index": 0,
                                "content_hash": "hash",
                                "sources": {
                                    "website_page": [
                                        [101, [3], "Admissions Trace Title"],
                                        [102, [5, 6], "Tuition Trace Title"],
                                    ],
                                    "website_program": [[201, [1], "MBA Trace Title"]],
                                },
                                "occurrences": 3,
                                "source_documents": 3,
                            }
                        ],
                    }
                ),
            },
        )
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [message_id]
    )

    sources = sources_by_message_id[message_id]
    assert [source.key for source in sources] == [
        "tool-chunks-v2:website_page:101:search:0",
        "tool-chunks-v2:website_page:102:search:0",
        "tool-chunks-v2:website_program:201:search:0",
    ]
    assert [source.title for source in sources] == [
        "Admissions Trace Title",
        "Tuition Trace Title",
        "MBA Trace Title",
    ]
    assert [source.url for source in sources] == [
        "https://demo-university.example.edu/admissions-updated",
        "https://demo-university.example.edu/tuition",
        "https://demo-university.example.edu/program/mba",
    ]
    assert [source.chunk for source in sources] == ["same chunk", "same chunk", "same chunk"]
    assert sources[0].search_query == "tuition"
    assert sources[1].search_query is None
    assert sources[2].search_query is None


@pytest.mark.asyncio
async def test_training_material_url_normalization_is_idempotent_for_demo_urls(
    transactional_session: AsyncSession,
) -> None:
    synthetic_url = "training-materials://Admissions/Guide%20%26%20Checklist.docx"
    demo_url = training_material_demo_url_from_url(synthetic_url)
    synthetic_message_id = uuid4()
    demo_message_id = uuid4()
    started_at = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)

    transactional_session.add_all(
        [
            OtelSpan(
                trace_id="trace-synthetic-training-material",
                span_id="tool-synthetic-training-material",
                message_id=synthetic_message_id,
                name="execute_tool retrieve_documents",
                start_time=started_at,
                attributes={
                    "gen_ai.tool.name": "retrieve_documents",
                    "gen_ai.tool.call.result": [
                        {
                            "type": "training_material",
                            "id": 10,
                            "title": "Guide",
                            "url": synthetic_url,
                        }
                    ],
                },
            ),
            OtelSpan(
                trace_id="trace-demo-training-material",
                span_id="tool-demo-training-material",
                message_id=demo_message_id,
                name="execute_tool retrieve_documents",
                start_time=started_at,
                attributes={
                    "gen_ai.tool.name": "retrieve_documents",
                    "gen_ai.tool.call.result": [
                        {"type": "training_material", "id": 11, "title": "Guide", "url": demo_url}
                    ],
                },
            ),
        ]
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [synthetic_message_id, demo_message_id]
    )

    assert sources_by_message_id[synthetic_message_id][0].url == demo_url
    assert sources_by_message_id[demo_message_id][0].url == demo_url


@pytest.mark.asyncio
async def test_tool_sources_used_batch_uses_all_traces_per_message(
    transactional_session: AsyncSession,
) -> None:
    first_message_id = uuid4()
    second_message_id = uuid4()
    started_at = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)

    transactional_session.add_all(
        [
            OtelSpan(
                trace_id="trace-old",
                span_id="tool-old",
                message_id=first_message_id,
                name="execute_tool list_catalog_pages",
                start_time=started_at,
                attributes={
                    "gen_ai.tool.name": "list_catalog_pages",
                    "gen_ai.tool.call.arguments": {},
                    "gen_ai.tool.call.result": [
                        {
                            "type": "catalog_page",
                            "id": 1,
                            "title": "Old Catalog Page",
                            "url": "https://catalog.demo-university.example.edu/old",
                        }
                    ],
                },
            ),
            OtelSpan(
                trace_id="trace-first",
                span_id="tool-first",
                message_id=first_message_id,
                name="execute_tool list_catalog_pages",
                start_time=started_at + timedelta(seconds=1),
                attributes={
                    "gen_ai.tool.name": "list_catalog_pages",
                    "gen_ai.tool.call.arguments": {},
                    "gen_ai.tool.call.result": [
                        {
                            "type": "catalog_page",
                            "id": 2,
                            "title": "First Catalog Page",
                            "url": "https://catalog.demo-university.example.edu/first",
                        }
                    ],
                },
            ),
            OtelSpan(
                trace_id="trace-second",
                span_id="tool-second",
                message_id=second_message_id,
                name="execute_tool list_catalog_pages",
                start_time=started_at + timedelta(seconds=2),
                attributes={
                    "gen_ai.tool.name": "list_catalog_pages",
                    "gen_ai.tool.call.arguments": {},
                    "gen_ai.tool.call.result": [
                        {
                            "type": "catalog_page",
                            "id": 3,
                            "title": "Second Catalog Page",
                            "url": "https://catalog.demo-university.example.edu/second",
                        }
                    ],
                },
            ),
        ]
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [first_message_id, second_message_id]
    )

    assert set(sources_by_message_id) == {first_message_id, second_message_id}
    assert [source.title for source in sources_by_message_id[first_message_id]] == [
        "Old Catalog Page",
        "First Catalog Page",
    ]
    assert sources_by_message_id[first_message_id][0].tool_call_id == "tool-old"
    assert sources_by_message_id[first_message_id][0].search_query is None
    assert sources_by_message_id[first_message_id][1].tool_call_id == "tool-first"
    assert sources_by_message_id[first_message_id][1].search_query is None
    assert [source.title for source in sources_by_message_id[second_message_id]] == [
        "Second Catalog Page"
    ]
    assert sources_by_message_id[second_message_id][0].tool_call_id == "tool-second"
    assert sources_by_message_id[second_message_id][0].search_query is None


@pytest.mark.asyncio
async def test_list_website_tools_project_candidate_sources(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        Document(
            type=DocumentType.WEBSITE_PAGE,
            id_=920007,
            source_key=document_source_key(
                DocumentType.WEBSITE_PAGE,
                920007,
                "Admissions",
                "https://demo-university.example.edu/admissions",
                "Admissions content",
            ),
            title="Admissions",
            url="https://demo-university.example.edu/admissions",
            markdown_content="Admissions content",
            token_count=2,
            character_count=18,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    transactional_session.add(
        OtelSpan(
            trace_id="trace-website-list",
            span_id="tool-website-list",
            message_id=message_id,
            name="execute_tool list_website_pages",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "list_website_pages",
                "gen_ai.tool.call.result": [[920007, "Admissions"]],
            },
        )
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [message_id]
    )

    assert [source.title for source in sources_by_message_id[message_id]] == ["Admissions"]
    assert (
        sources_by_message_id[message_id][0].url == "https://demo-university.example.edu/admissions"
    )
    assert sources_by_message_id[message_id][0].tool_name == "list_website_pages"


@pytest.mark.asyncio
async def test_list_website_tools_fail_loudly_on_malformed_candidate_row(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        OtelSpan(
            trace_id="trace-website-list-malformed",
            span_id="tool-website-list-malformed",
            message_id=message_id,
            name="execute_tool list_website_pages",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "list_website_pages",
                "gen_ai.tool.call.result": [["not-an-id", "Admissions"]],
            },
        )
    )
    await transactional_session.flush()

    with pytest.raises(TypeError, match="Malformed website_page ID/title source row"):
        await get_tool_sources_used_by_message_ids(transactional_session, [message_id])


@pytest.mark.asyncio
async def test_list_catalog_courses_projects_candidate_sources(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        Document(
            type=DocumentType.CATALOG_COURSE,
            id_=12345,
            source_key=document_source_key(
                DocumentType.CATALOG_COURSE,
                12345,
                "ACC 111 - Financial Accounting",
                "https://catalog.demo-university.example.edu/preview_course.php?catoid=1&coid=12345",
                "Course content",
            ),
            title="ACC 111 - Financial Accounting",
            url="https://catalog.demo-university.example.edu/preview_course.php?catoid=1&coid=12345",
            markdown_content="Course content",
            token_count=2,
            character_count=14,
            title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    transactional_session.add(
        OtelSpan(
            trace_id="trace-catalog-courses",
            span_id="tool-catalog-courses",
            message_id=message_id,
            name="execute_tool list_catalog_courses",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "list_catalog_courses",
                "gen_ai.tool.call.result": [
                    {
                        "type": "catalog_course",
                        "id": 12345,
                        "title": "ACC 111 - Financial Accounting",
                    }
                ],
            },
        )
    )
    await transactional_session.flush()

    sources_by_message_id = await get_tool_sources_used_by_message_ids(
        transactional_session, [message_id]
    )

    assert [source.title for source in sources_by_message_id[message_id]] == [
        "ACC 111 - Financial Accounting"
    ]
    assert sources_by_message_id[message_id][0].url.endswith("coid=12345")
    assert sources_by_message_id[message_id][0].tool_name == "list_catalog_courses"


@pytest.mark.asyncio
async def test_list_catalog_courses_fails_loudly_on_malformed_candidate_row(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        OtelSpan(
            trace_id="trace-catalog-courses-malformed",
            span_id="tool-catalog-courses-malformed",
            message_id=message_id,
            name="execute_tool list_catalog_courses",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "list_catalog_courses",
                "gen_ai.tool.call.result": [{"type": "catalog_course", "id": "bad"}],
            },
        )
    )
    await transactional_session.flush()

    with pytest.raises(TypeError, match="Malformed source"):
        await get_tool_sources_used_by_message_ids(transactional_session, [message_id])


@pytest.mark.asyncio
async def test_tool_sources_used_fails_loudly_on_invalid_search_argument_json(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        OtelSpan(
            trace_id="trace-invalid-arguments",
            span_id="tool-invalid-arguments",
            message_id=message_id,
            name="execute_tool find_document_titles",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "find_document_titles",
                "gen_ai.tool.call.arguments": "not-json",
                "gen_ai.tool.call.result": "No matching document titles found.",
            },
        )
    )
    await transactional_session.flush()

    with pytest.raises(ValueError, match=r"gen_ai\.tool\.call\.arguments"):
        await get_tool_sources_used_by_message_ids(transactional_session, [message_id])


@pytest.mark.asyncio
async def test_tool_sources_used_fails_loudly_on_invalid_json_tool_result(
    transactional_session: AsyncSession,
) -> None:
    message_id = uuid4()
    transactional_session.add(
        OtelSpan(
            trace_id="trace-invalid-result",
            span_id="tool-invalid-result",
            message_id=message_id,
            name="execute_tool list_catalog_pages",
            start_time=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
            attributes={
                "gen_ai.tool.name": "list_catalog_pages",
                "gen_ai.tool.call.arguments": {},
                "gen_ai.tool.call.result": "not-json",
            },
        )
    )
    await transactional_session.flush()

    with pytest.raises(ValueError, match=r"gen_ai\.tool\.call\.result"):
        await get_tool_sources_used_by_message_ids(transactional_session, [message_id])
