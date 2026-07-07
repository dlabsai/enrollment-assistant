from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.document import (
    _find_document_chunks_db,  # pyright: ignore[reportPrivateUsage]
    _find_document_titles_db,  # pyright: ignore[reportPrivateUsage]
    _render_training_materials_tree,  # pyright: ignore[reportPrivateUsage]
    _retrieve_documents_db,  # pyright: ignore[reportPrivateUsage]
    find_document_chunks,
    find_document_chunks_internal,
    find_document_titles,
    find_document_titles_internal,
    list_training_materials_tree,
)
from app.models import Document as DBDocument
from app.models import DocumentContentChunk, DocumentType
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.rag.source_keys import document_source_key


def _fake_openai_with_embedding() -> MagicMock:
    openai = MagicMock()
    openai.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS)]
        )
    )
    return openai


def _db_document(
    *, document_type: DocumentType, document_id: int, title: str, url: str, markdown_content: str
) -> DBDocument:
    db_document = DBDocument(
        type=document_type,
        id_=document_id,
        source_key=document_source_key(document_type, document_id, title, url, markdown_content),
        title=title,
        url=url,
        markdown_content=markdown_content,
        token_count=3,
        character_count=len(markdown_content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    db_document.document_content_chunks.append(
        DocumentContentChunk(
            sequence_number=0,
            content=markdown_content,
            token_count=3,
            character_count=len(markdown_content),
            content_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    return db_document


def test_document_search_tools_expose_only_supported_arguments() -> None:
    assert "limit" not in signature(find_document_chunks).parameters
    assert "limit" not in signature(find_document_titles).parameters
    assert "limit" not in signature(find_document_chunks_internal).parameters
    assert "limit" not in signature(find_document_titles_internal).parameters
    assert "document_types" not in signature(find_document_chunks).parameters
    assert "document_types" not in signature(find_document_titles).parameters
    assert "document_types" in signature(find_document_chunks_internal).parameters
    assert "document_types" in signature(find_document_titles_internal).parameters


def test_render_training_materials_tree_deduplicates_folder_paths() -> None:
    tree = _render_training_materials_tree(
        [
            (
                -101,
                "Graduate Admissions Guide 3.5.2026",
                "Grad Admissions Online/00 - Admissions Guides/"
                "Graduate Admissions Guide 3.5.2026.pdf",
            ),
            (
                -202,
                "MBA",
                "Grad Admissions Online/02-Degree Program Resources/"
                "Malcolm Baldridge School/MBA.pdf",
            ),
        ]
    )

    assert tree == (
        "- Grad Admissions Online/\n"
        "  - 00 - Admissions Guides/\n"
        "    - [-101] Graduate Admissions Guide 3.5.2026.pdf\n"
        "  - 02-Degree Program Resources/\n"
        "    - Malcolm Baldridge School/\n"
        "      - [-202] MBA.pdf"
    )


def test_render_training_materials_tree_sanitizes_display_whitespace() -> None:
    tree = _render_training_materials_tree(
        [(-303, "ignored title", "Root\tFolder/Sub\nFolder/ File\r\nName  With  Spaces.pdf ")]
    )

    assert tree == "- Root Folder/\n  - Sub Folder/\n    - [-303] File Name With Spaces.pdf"


def test_render_training_materials_tree_escapes_leading_ordered_list_markers() -> None:
    tree = _render_training_materials_tree(
        [
            (
                -404,
                "ignored title",
                "Root/2. Process and Procedure/1. Lead Emails/Application Received.docx",
            )
        ]
    )

    assert tree == (
        "- Root/\n"
        "  - 2\\. Process and Procedure/\n"
        "    - 1\\. Lead Emails/\n"
        "      - [-404] Application Received.docx"
    )


@pytest.mark.asyncio
async def test_list_training_materials_tree_queries_training_materials_only() -> None:
    row = MagicMock()
    row.id_ = -202
    row.title = "MBA"
    row.url = "training-materials://Grad%20Admissions%20Online/MBA.pdf"

    execute_result = MagicMock()
    execute_result.all.return_value = [row]

    session = AsyncMock()
    session.execute.return_value = execute_result

    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = session

    deps = MagicMock()
    deps.open_tool_session.return_value = context_manager
    ctx = MagicMock()
    ctx.deps = deps

    result = await list_training_materials_tree(ctx)

    assert result == "Document count: 1\n\n- Grad Admissions Online/\n  - [-202] MBA.pdf"
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    assert str(DocumentType.TRAINING_MATERIAL.value) in str(compiled)


@pytest.mark.asyncio
async def test_retrieve_documents_internal_returns_demo_training_material_url(
    transactional_session: AsyncSession,
) -> None:
    document_url = "training-materials://Unit%20Test%20Materials/Retrieve%20Demo%20URL%20Test.pdf"
    markdown_content = "# Graduate Admissions Guide"
    document = DBDocument(
        type=DocumentType.TRAINING_MATERIAL,
        id_=-505,
        source_key=document_source_key(
            DocumentType.TRAINING_MATERIAL,
            -505,
            "Retrieve Demo URL Test",
            document_url,
            markdown_content,
        ),
        title="Retrieve Demo URL Test",
        url=document_url,
        markdown_content=markdown_content,
        token_count=3,
        character_count=15,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    document.document_content_chunks.append(
        DocumentContentChunk(
            sequence_number=0,
            content="Graduate Admissions Guide",
            token_count=2,
            character_count=13,
            content_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    transactional_session.add(document)
    await transactional_session.flush()

    documents, not_found_ids, truncated_info = await _retrieve_documents_db(
        transactional_session, training_material_ids=[-505]
    )

    assert not_found_ids is None
    assert truncated_info is None
    assert len(documents) == 1
    assert documents[0].url == (
        "https://demo-university.example.edu/internal/training-materials/"
        "Unit%20Test%20Materials/Retrieve%20Demo%20URL%20Test.pdf"
    )


@pytest.mark.asyncio
async def test_find_document_chunks_filters_by_document_type(
    transactional_session: AsyncSession,
) -> None:
    training_material = _db_document(
        document_type=DocumentType.TRAINING_MATERIAL,
        document_id=-606,
        title="Training Payment Plan",
        url="training-materials://Payment%20Plan.pdf",
        markdown_content="Reviewed internal payment plan guidance",
    )
    website_page = _db_document(
        document_type=DocumentType.WEBSITE_PAGE,
        document_id=607,
        title="Public Payment Plan",
        url="https://demo-university.example.edu/payment-plan/",
        markdown_content="Public payment plan page",
    )
    transactional_session.add_all([training_material, website_page])
    await transactional_session.flush()

    payload = await _find_document_chunks_db(
        transactional_session,
        _fake_openai_with_embedding(),
        "payment plan",
        is_internal=True,
        document_types=[DocumentType.TRAINING_MATERIAL],
    )
    results = payload.representative_results

    assert results
    assert all(result.type == DocumentType.TRAINING_MATERIAL for result in results)
    assert any(result.id == -606 for result in results)


@pytest.mark.asyncio
async def test_find_document_titles_skips_embedding_when_no_requested_types_are_allowed(
    transactional_session: AsyncSession,
) -> None:
    openai = _fake_openai_with_embedding()

    results = await _find_document_titles_db(
        transactional_session,
        openai,
        "training guide",
        is_internal=False,
        document_types=[DocumentType.TRAINING_MATERIAL],
    )

    assert results == []
    openai.embeddings.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_document_titles_filters_by_document_type(
    transactional_session: AsyncSession,
) -> None:
    training_material = _db_document(
        document_type=DocumentType.TRAINING_MATERIAL,
        document_id=-707,
        title="Training MBA Guide",
        url="training-materials://MBA%20Guide.pdf",
        markdown_content="Reviewed internal MBA guidance",
    )
    website_program = _db_document(
        document_type=DocumentType.WEBSITE_PROGRAM,
        document_id=708,
        title="Public MBA Program",
        url="https://demo-university.example.edu/academics/mba/",
        markdown_content="Public MBA program page",
    )
    transactional_session.add_all([training_material, website_program])
    await transactional_session.flush()

    results = await _find_document_titles_db(
        transactional_session,
        _fake_openai_with_embedding(),
        "mba",
        is_internal=True,
        document_types=[DocumentType.WEBSITE_PROGRAM],
    )

    assert results
    assert all(result.type == DocumentType.WEBSITE_PROGRAM for result in results)
    assert any(result.id == 708 and result.title == "Public MBA Program" for result in results)
