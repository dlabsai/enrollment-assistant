from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.evals.rag_copy import (
    EvalRagCopyLogCallback,
    EvalRagCopyProgressCallback,
    EvalRagCopyProgressSnapshot,
    EvalRagCopyProgressStep,
    EvalRagCopyResult,
)
from app.main import app
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
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.rag.source_keys import document_source_key
from app.utils import current_time_utc
from tests.api.auth_helpers import authenticate_client


async def _create_user(
    session: AsyncSession, *, group_slug: SystemGroupSlug, email_prefix: str
) -> User:
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=f"{email_prefix}-{uuid4()}@example.com",
        name=f"{group_slug.value.title()} User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_document(
    session: AsyncSession,
    *,
    document_type: DocumentType,
    source_id: int,
    title: str,
    markdown_content: str | None = None,
    url: str | None = None,
) -> Document:
    content = markdown_content if markdown_content is not None else f"# {title}\n\nBody"
    document_url = (
        url if url is not None else f"https://example.com/{document_type.value}/{source_id}"
    )
    document = Document(
        type=document_type,
        id_=source_id,
        source_key=document_source_key(document_type, source_id, title, document_url, content),
        title=title,
        url=document_url,
        markdown_content=content,
        token_count=10,
        character_count=len(content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    document.document_content_chunks.append(
        DocumentContentChunk(
            sequence_number=0,
            content=f"{title} chunk",
            token_count=3,
            character_count=12,
            content_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    session.add(document)
    await session.flush()
    return document


@pytest.mark.asyncio
async def test_rag_documents_require_access_rag_viewer_permission(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="rag-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/rag/documents")

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_rag_jobs_require_access_rag_permission(transactional_session: AsyncSession) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="rag-jobs-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/rag/jobs")

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_rag_jobs_list_and_detail_include_document_changes(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-jobs-admin"
    )
    now = current_time_utc()
    job = RagBuildJob(
        job_name="api_rag_build",
        trigger="manual",
        status="completed",
        force_rebuild=False,
        started_by_user_id=admin.id,
        started_at=now,
        finished_at=now,
        duration_ms=123.0,
    )
    transactional_session.add(job)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            RagBuildJobStep(
                job_id=job.id,
                step_key="demo_corpus_ingest",
                label="Demo corpus ingest",
                status="completed",
                started_at=now,
                finished_at=now,
            ),
            RagBuildJobSourceStat(
                job_id=job.id,
                source_name="Website pages",
                document_type="website_page",
                new_count=1,
                changed_count=1,
                deleted_count=1,
                unchanged_count=7,
                source_document_count=9,
                existing_document_count=9,
            ),
            RagBuildJobDocumentChange(
                job_id=job.id,
                source_name="Website pages",
                document_type="website_page",
                change_type="changed",
                source_id=42,
                source_key="website_page:42",
                title="Updated tuition page",
                url="https://demo-university.example.edu/tuition/",
                previous_title="Old tuition page",
                previous_url="https://demo-university.example.edu/old-tuition/",
                source_updated_at=now,
                previous_source_updated_at=now,
            ),
        ]
    )
    await transactional_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        list_response = await client.get("/api/rag/jobs")
        detail_response = await client.get(f"/api/rag/jobs/{job.id}")

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] >= 1
    listed_job = next(item for item in list_payload["items"] if item["id"] == str(job.id))
    assert listed_job["total_new"] == 1
    assert listed_job["total_changed"] == 1
    assert listed_job["total_deleted"] == 1
    assert listed_job["started_by"]["email"] == admin.email

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["source_stats"] == [
        {
            "source_name": "Website pages",
            "document_type": "website_page",
            "new_count": 1,
            "changed_count": 1,
            "deleted_count": 1,
            "unchanged_count": 7,
            "source_document_count": 9,
            "existing_document_count": 9,
        }
    ]
    assert detail_payload["document_changes"][0]["title"] == "Updated tuition page"
    assert (
        detail_payload["document_changes"][0]["previous_url"]
        == "https://demo-university.example.edu/old-tuition/"
    )


@pytest.mark.asyncio
async def test_rag_documents_list_returns_expected_shape(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-list"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"limit": 10, "offset": 0, "sort_by": "token_count", "descending": "true"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("total"), int)
    assert isinstance(payload.get("items"), list)

    items = payload["items"]
    if items:
        first_item = items[0]
        assert first_item["source_type"] in {"website_page", "website_program", "training_material"}
        assert isinstance(first_item["token_count"], int)
        assert isinstance(first_item["character_count"], int)
        assert isinstance(first_item["chunk_count"], int)
        assert "created_at" in first_item
        assert "modified_at" in first_item

    token_counts = [item["token_count"] for item in items]
    assert token_counts == sorted(token_counts, reverse=True)


@pytest.mark.asyncio
async def test_rag_documents_exact_search_uses_case_insensitive_substring_matching(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-exact-search",
    )
    matching_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9301,
        title="Exact Search Match",
        markdown_content="# Exact Search Match\n\nThe student needs Alpha Beta support.",
    )
    nonmatching_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9302,
        title="Exact Search Nonmatch",
        markdown_content="# Exact Search Nonmatch\n\nThe student needs Alpha\nBeta support.",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"search": "alpha beta", "search_mode": "exact", "types": "website_page"},
        )

    assert response.status_code == 200
    matching_ids = {item["id"] for item in response.json()["items"]}
    assert str(matching_document.id) in matching_ids
    assert str(nonmatching_document.id) not in matching_ids


@pytest.mark.asyncio
async def test_rag_documents_full_text_search_matches_tokens_and_ranks_title_matches_first(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-full-text-search",
    )
    body_match = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9303,
        title="Full Text Body Match",
        markdown_content="# Full Text Body Match\n\nThe student needs Gamma\nDelta support.",
    )
    title_match = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9304,
        title="Gamma Delta Full Text Title Match",
        markdown_content="# Title Match\n\nOther body text.",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"search": "gamma delta", "search_mode": "full_text", "types": "website_page"},
        )

    assert response.status_code == 200
    matching_ids = [item["id"] for item in response.json()["items"]]
    assert matching_ids.index(str(title_match.id)) < matching_ids.index(str(body_match.id))


@pytest.mark.asyncio
async def test_rag_documents_list_includes_catalog(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-catalog"
    )
    document = await _create_document(
        transactional_session,
        document_type=DocumentType.CATALOG_COURSE,
        source_id=9001,
        title="Catalog Course Test",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"types": "catalog_course", "search": "Catalog Course Test"},
        )
        detail_response = await client.get(f"/api/rag/documents/{document.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source_type"] == "catalog_course"
    assert detail_response.status_code == 200
    assert detail_response.json()["source_type"] == "catalog_course"


@pytest.mark.asyncio
async def test_rag_document_detail_converts_training_material_url_to_demo_url(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-training-url",
    )
    document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9103,
        title="Graduate Planning Guide 3.5.2026",
    )
    document.url = (
        "training-materials://Grad%20Admissions%20Online/00%20-%20Planning%20Guides/"
        "Graduate%20Planning%20Guide%203.5.2026.pdf"
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(f"/api/rag/documents/{document.id}")

    assert response.status_code == 200
    assert response.json()["url"] == (
        "https://demo-university.example.edu/internal/training-materials/"
        "Grad%20Admissions%20Online/00%20-%20Planning%20Guides/"
        "Graduate%20Planning%20Guide%203.5.2026.pdf"
    )


@pytest.mark.asyncio
async def test_rag_documents_list_filters_documents_by_file_extension(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-training-extension",
    )
    pdf_document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9110,
        title="Extension Filter Training PDF",
        url="training-materials://Folder/Training%20PDF.PDF",
    )
    word_document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9111,
        title="Extension Filter Training Word",
        url="training-materials://Folder/Training%20Word.docx",
    )
    website_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9112,
        title="Extension Filter Website PDF-like URL",
        url="https://example.com/files/website.pdf",
    )
    root_pdf_document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9114,
        title="Extension Filter Root Training PDF",
        url="training-materials://Root%20Training%20PDF.pdf",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={
                "file_extension": ".pdf",
                "search": "Extension Filter",
                "sort_by": "title",
                "descending": "false",
            },
        )

    assert response.status_code == 200
    matching_ids = {item["id"] for item in response.json()["items"]}
    assert str(pdf_document.id) in matching_ids
    assert str(root_pdf_document.id) in matching_ids
    assert str(word_document.id) not in matching_ids
    assert str(website_document.id) not in matching_ids


@pytest.mark.asyncio
async def test_rag_training_material_file_extension_preserves_hash_filename(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-training-hash-extension",
    )
    document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9115,
        title="New  Unconverted Leads #4 - approved",
        url=("training-materials://Folder/New%20%20Unconverted%20Leads%20#4%20-%20approved.docx"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        list_response = await client.get(
            "/api/rag/documents", params={"file_extension": "docx", "search": "Unconverted Leads"}
        )
        tree_response = await client.get("/api/rag/documents/tree")

    assert list_response.status_code == 200
    assert str(document.id) in {item["id"] for item in list_response.json()["items"]}
    assert tree_response.status_code == 200
    folder = next(node for node in tree_response.json() if node["label"] == "Training materials")[
        "children"
    ][0]
    assert any(
        child["label"] == "New  Unconverted Leads #4 - approved.docx"
        and child["document_id"] == str(document.id)
        for child in folder["children"]
    )


@pytest.mark.asyncio
async def test_rag_document_file_extensions_classifies_content_types(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-training-extension-options",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9120,
        title="Training PDF Options",
        url="training-materials://Folder/Training%20PDF%20Options.PDF",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9121,
        title="Training Word Options",
        url="training-materials://Folder/Training%20Word%20Options.docx",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9122,
        title="Website PDF Options",
        url="https://example.com/files/website-options.pdf",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9126,
        title="Website Calendar ICS Options",
        url="https://example.com/files/calendar.ics",
    )
    html_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9123,
        title="Website HTML Options",
        url="https://example.com/no-extension-page",
    )
    php_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9124,
        title="Website PHP Options",
        url="https://example.com/page.php",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/rag/documents/file-extensions")
        html_response = await client.get(
            "/api/rag/documents",
            params={"file_extension": "html", "search": "Website HTML Options"},
        )
        php_response = await client.get(
            "/api/rag/documents", params={"file_extension": "html", "search": "Website PHP Options"}
        )
    assert response.status_code == 200
    extensions = response.json()["extensions"]
    assert "pdf" in extensions
    assert "docx" in extensions
    assert "html" in extensions
    assert "ics" not in extensions
    assert "php" not in extensions
    assert html_response.status_code == 200
    assert str(html_document.id) in {item["id"] for item in html_response.json()["items"]}
    assert php_response.status_code == 200
    assert str(php_document.id) in {item["id"] for item in php_response.json()["items"]}


@pytest.mark.asyncio
async def test_rag_documents_list_includes_catalog_documents(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-catalog-always",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.CATALOG_COURSE,
        source_id=9002,
        title="Always Available Catalog Course Test",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"types": "catalog_course", "search": "Always Available Catalog Course Test"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source_type"] == "catalog_course"


@pytest.mark.asyncio
async def test_rag_documents_tree_groups_sources_and_training_material_paths(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-tree"
    )
    website_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9401,
        title="Tree Website Page",
    )
    catalog_document = await _create_document(
        transactional_session,
        document_type=DocumentType.CATALOG_COURSE,
        source_id=9402,
        title="Tree Catalog Course",
    )
    training_document = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9403,
        title="Training File Title",
    )
    training_document.url = "training-materials://Folder%20A/Folder%20B/Training%20File.pdf"
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get("/api/rag/documents/tree")

    assert response.status_code == 200
    tree = response.json()
    roots = {node["label"]: node for node in tree}

    website_pages = next(
        node for node in roots["Website"]["children"] if node["label"] == "Website pages"
    )
    assert any(
        child["document_id"] == str(website_document.id) for child in website_pages["children"]
    )

    catalog_courses = next(
        node for node in roots["Catalog"]["children"] if node["label"] == "Catalog courses"
    )
    assert any(
        child["document_id"] == str(catalog_document.id) for child in catalog_courses["children"]
    )

    folder_a = next(
        node for node in roots["Training materials"]["children"] if node["label"] == "Folder A"
    )
    folder_b = next(node for node in folder_a["children"] if node["label"] == "Folder B")
    assert any(
        child["label"] == "Training File.pdf" and child["document_id"] == str(training_document.id)
        for child in folder_b["children"]
    )


@pytest.mark.asyncio
async def test_rag_documents_list_supports_url_sort(transactional_session: AsyncSession) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-url-sort"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents",
            params={"limit": 50, "offset": 0, "sort_by": "url", "descending": "false"},
        )

    assert response.status_code == 200
    items = response.json()["items"]
    urls = [item["url"] for item in items]
    assert urls == sorted(urls)


@pytest.mark.asyncio
async def test_rag_documents_list_supports_source_key_and_excluded_sort(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-exclusion-sort",
    )
    later_source_key_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9702,
        title="Source Key Sort Marker Later",
    )
    earlier_source_key_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9701,
        title="Source Key Sort Marker Earlier",
    )
    included_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9711,
        title="Status Sort Marker Included",
    )
    excluded_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9712,
        title="Status Sort Marker Excluded",
    )
    lower_source_id_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PROGRAM,
        source_id=9721,
        title="Source Metadata Sort Marker Lower ID",
    )
    higher_source_id_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9722,
        title="Source Metadata Sort Marker Higher ID",
    )
    transactional_session.add(
        RagDocumentExclusion(
            source_key=excluded_document.source_key,
            reason="Test exclusion",
            created_by_user_id=admin.id,
        )
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        source_key_response = await client.get(
            "/api/rag/documents",
            params={
                "descending": "false",
                "search": "Source Key Sort Marker",
                "sort_by": "source_key",
                "types": "website_page",
            },
        )
        status_response = await client.get(
            "/api/rag/documents",
            params={
                "descending": "true",
                "search": "Status Sort Marker",
                "sort_by": "excluded",
                "types": "website_page",
            },
        )
        source_type_response = await client.get(
            "/api/rag/documents",
            params={
                "descending": "false",
                "search": "Source Metadata Sort Marker",
                "sort_by": "source_type",
            },
        )
        source_id_response = await client.get(
            "/api/rag/documents",
            params={
                "descending": "false",
                "search": "Source Metadata Sort Marker",
                "sort_by": "source_id",
            },
        )

    assert source_key_response.status_code == 200
    assert [item["id"] for item in source_key_response.json()["items"]] == [
        str(earlier_source_key_document.id),
        str(later_source_key_document.id),
    ]

    assert status_response.status_code == 200
    status_items = status_response.json()["items"]
    assert [item["id"] for item in status_items] == [
        str(excluded_document.id),
        str(included_document.id),
    ]

    assert source_type_response.status_code == 200
    assert [item["id"] for item in source_type_response.json()["items"]] == [
        str(higher_source_id_document.id),
        str(lower_source_id_document.id),
    ]

    assert source_id_response.status_code == 200
    assert [item["id"] for item in source_id_response.json()["items"]] == [
        str(lower_source_id_document.id),
        str(higher_source_id_document.id),
    ]


@pytest.mark.asyncio
async def test_rag_document_chunks_support_document_metadata_sort(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-chunk-metadata-sort",
    )
    lower_source_id_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PROGRAM,
        source_id=9731,
        title="Chunk Source Metadata Sort Marker Lower ID",
    )
    higher_source_id_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9732,
        title="Chunk Source Metadata Sort Marker Higher ID",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        source_type_response = await client.get(
            "/api/rag/documents/chunks",
            params={
                "descending": "false",
                "search": "Chunk Source Metadata Sort Marker",
                "sort_by": "source_type",
            },
        )
        source_id_response = await client.get(
            "/api/rag/documents/chunks",
            params={
                "descending": "false",
                "search": "Chunk Source Metadata Sort Marker",
                "sort_by": "source_id",
            },
        )

    assert source_type_response.status_code == 200
    assert [item["document"]["id"] for item in source_type_response.json()["items"]] == [
        str(higher_source_id_document.id),
        str(lower_source_id_document.id),
    ]

    assert source_id_response.status_code == 200
    assert [item["document"]["id"] for item in source_id_response.json()["items"]] == [
        str(lower_source_id_document.id),
        str(higher_source_id_document.id),
    ]


@pytest.mark.asyncio
async def test_rag_document_exclusion_events_support_source_type_sort(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-history-type-sort",
    )
    page_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9741,
        title="History Type Sort Marker Page",
    )
    program_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PROGRAM,
        source_id=9742,
        title="History Type Sort Marker Program",
    )
    transactional_session.add_all(
        [
            RagDocumentExclusionEvent(
                source_key=program_document.source_key,
                action="excluded",
                reason="Test exclusion",
                document_title=program_document.title,
                document_url=program_document.url,
                source_type=program_document.type.value,
                created_by_user_id=admin.id,
            ),
            RagDocumentExclusionEvent(
                source_key=page_document.source_key,
                action="excluded",
                reason="Test exclusion",
                document_title=page_document.title,
                document_url=page_document.url,
                source_type=page_document.type.value,
                created_by_user_id=admin.id,
            ),
        ]
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents/exclusion-events",
            params={
                "descending": "false",
                "search": "History Type Sort Marker",
                "sort_by": "source_type",
            },
        )

    assert response.status_code == 200
    assert [item["source_type"] for item in response.json()["items"]] == [
        DocumentType.WEBSITE_PAGE.value,
        DocumentType.WEBSITE_PROGRAM.value,
    ]


@pytest.mark.asyncio
async def test_rag_document_detail_returns_chunks_for_existing_document(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-detail"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)

        list_response = await client.get("/api/rag/documents", params={"limit": 1, "offset": 0})
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        if not items:
            pytest.skip("No RAG documents available in the test database")

        document_id = items[0]["id"]
        detail_response = await client.get(f"/api/rag/documents/{document_id}")

    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert isinstance(payload["markdown_content"], str)
    assert payload["chunk_count"] == len(payload["chunks"])

    sequence_numbers = [chunk["sequence_number"] for chunk in payload["chunks"]]
    assert sequence_numbers == sorted(sequence_numbers)


@pytest.mark.asyncio
async def test_rag_similarity_search_requires_access_rag_viewer_permission(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="rag-sim-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.get("/api/rag/documents/similarity", params={"query": "tuition"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_rag_similarity_search_returns_chunk_matches(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-sim-admin"
    )
    document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9101,
        title="Similarity Search Test",
    )

    class _FakeEmbeddingData:
        def __init__(self) -> None:
            self.embedding = [0.0] * EMBEDDING_VECTOR_DIMENSIONS

    class _FakeEmbeddingResponse:
        def __init__(self) -> None:
            self.data = [_FakeEmbeddingData()]

    class _FakeEmbeddings:
        async def create(self, **kwargs: object) -> _FakeEmbeddingResponse:
            assert kwargs["input"] == "similarity test"
            assert kwargs["dimensions"] == EMBEDDING_VECTOR_DIMENSIONS
            return _FakeEmbeddingResponse()

    class _FakeOpenAI:
        embeddings = _FakeEmbeddings()

    monkeypatch.setattr("app.api.routes.rag.get_azure_openai_client", _FakeOpenAI)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents/similarity",
            params={"query": "similarity test", "limit": 5, "types": "website_page"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    matching_item = next(item for item in payload["items"] if item["id"] == str(document.id))
    assert matching_item["source_type"] == "website_page"
    assert matching_item["source_id"] == 9101
    assert matching_item["sequence_number"] == 0
    assert matching_item["content"] == "Similarity Search Test chunk"
    assert matching_item["chunk_token_count"] == 3
    assert isinstance(matching_item["distance"], float)


@pytest.mark.asyncio
async def test_rag_similarity_search_includes_catalog(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-sim-catalog-always",
    )
    await _create_document(
        transactional_session,
        document_type=DocumentType.CATALOG_COURSE,
        source_id=9102,
        title="Similarity Catalog Course Test",
    )

    class _FakeEmbeddingData:
        def __init__(self) -> None:
            self.embedding = [0.0] * EMBEDDING_VECTOR_DIMENSIONS

    class _FakeEmbeddingResponse:
        def __init__(self) -> None:
            self.data = [_FakeEmbeddingData()]

    class _FakeEmbeddings:
        async def create(self, **_kwargs: object) -> _FakeEmbeddingResponse:
            return _FakeEmbeddingResponse()

    class _FakeOpenAI:
        embeddings = _FakeEmbeddings()

    monkeypatch.setattr("app.api.routes.rag.get_azure_openai_client", _FakeOpenAI)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(
            "/api/rag/documents/similarity", params={"query": "catalog", "types": "catalog_course"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["source_type"] == "catalog_course"


@pytest.mark.asyncio
async def test_copy_eval_rag_requires_rag_access_permission(
    transactional_session: AsyncSession,
) -> None:
    user = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.USER, email_prefix="rag-copy-user"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, user.id)
        response = await client.post("/api/rag/eval-rag/copy", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


@pytest.mark.asyncio
async def test_copy_eval_rag_returns_copied_counts(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-copy-admin"
    )

    async def fake_copy_runtime_rag_to_eval_db(session: AsyncSession) -> EvalRagCopyResult:
        assert session is transactional_session
        return EvalRagCopyResult(
            documents=3, chunks=7, guardrail_registries=2, document_exclusions=1
        )

    monkeypatch.setattr(
        "app.api.routes.rag.copy_runtime_rag_to_eval_db", fake_copy_runtime_rag_to_eval_db
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/eval-rag/copy", json={})

    assert response.status_code == 200
    assert response.json() == {
        "copied": {"documents": 3, "chunks": 7, "guardrail_registries": 2, "document_exclusions": 1}
    }


@pytest.mark.asyncio
async def test_copy_eval_rag_streams_progress_logs_and_counts(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-copy-stream-admin",
    )

    async def fake_copy_runtime_rag_to_eval_db(
        session: AsyncSession,
        *,
        progress_callback: EvalRagCopyProgressCallback | None = None,
        log_callback: EvalRagCopyLogCallback | None = None,
    ) -> EvalRagCopyResult:
        assert session is transactional_session
        assert progress_callback is not None
        assert log_callback is not None
        await progress_callback(
            EvalRagCopyProgressSnapshot(
                steps=[
                    EvalRagCopyProgressStep(
                        key="copy_documents", label="Copy documents", status="running"
                    )
                ],
                current_step="copy_documents",
                finished_steps=0,
                total_steps=1,
            )
        )
        await log_callback("Copied 3/3 documents.")
        return EvalRagCopyResult(
            documents=3, chunks=7, guardrail_registries=2, document_exclusions=1
        )

    monkeypatch.setattr(
        "app.api.routes.rag.copy_runtime_rag_to_eval_db", fake_copy_runtime_rag_to_eval_db
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.post("/api/rag/eval-rag/copy/stream", json={})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    content = response.text
    assert 'event: status\ndata: {"status": "start"}' in content
    assert 'event: progress\ndata: {"steps": [{"key": "copy_documents"' in content
    assert '"current_step": "copy_documents"' in content
    assert 'event: log\ndata: {"stream": "stdout", "message": "Copied 3/3 documents."}' in content
    expected_result_message = (
        "Eval KB synced: 3 documents, 7 chunks, 1 document exclusion, "
        "and 2 guardrail registries copied."
    )
    assert expected_result_message in content
    assert 'event: status\ndata: {"status": "complete", "exit_code": 0}' in content


@pytest.mark.asyncio
async def test_rag_documents_list_filters_by_exclusion_status(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-exclusion-filter",
    )
    included_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9601,
        title="Exclusion Filter Included",
    )
    excluded_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9602,
        title="Exclusion Filter Excluded",
    )
    transactional_session.add(
        RagDocumentExclusion(
            source_key=excluded_document.source_key,
            reason="Test exclusion",
            created_by_user_id=admin.id,
        )
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        included_response = await client.get(
            "/api/rag/documents",
            params={"search": "Exclusion Filter", "exclusion": "included", "types": "website_page"},
        )
        excluded_response = await client.get(
            "/api/rag/documents",
            params={"search": "Exclusion Filter", "exclusion": "excluded", "types": "website_page"},
        )

    assert included_response.status_code == 200
    included_ids = {item["id"] for item in included_response.json()["items"]}
    assert str(included_document.id) in included_ids
    assert str(excluded_document.id) not in included_ids

    assert excluded_response.status_code == 200
    excluded_items = excluded_response.json()["items"]
    excluded_ids = {item["id"] for item in excluded_items}
    assert str(included_document.id) not in excluded_ids
    assert str(excluded_document.id) in excluded_ids
    excluded_item = next(item for item in excluded_items if item["id"] == str(excluded_document.id))
    assert excluded_item["excluded"] is True
    assert excluded_item["exclusion_reason"] == "Test exclusion"


@pytest.mark.asyncio
async def test_rag_documents_list_returns_filtered_exclusion_summary(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-exclusion-summary",
    )
    included_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9821,
        title="Exclusion Summary Included",
    )
    excluded_page = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9822,
        title="Exclusion Summary Page",
    )
    excluded_training = await _create_document(
        transactional_session,
        document_type=DocumentType.TRAINING_MATERIAL,
        source_id=-9823,
        title="Exclusion Summary Training",
    )
    included_document.token_count = 11
    excluded_page.token_count = 17
    excluded_training.token_count = 23
    excluded_page.document_content_chunks.append(
        DocumentContentChunk(
            sequence_number=1,
            content="Exclusion Summary Page second chunk",
            token_count=5,
            character_count=36,
            content_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
        )
    )
    transactional_session.add_all(
        [
            RagDocumentExclusion(
                source_key=excluded_page.source_key,
                reason="Test exclusion",
                created_by_user_id=admin.id,
            ),
            RagDocumentExclusion(
                source_key=excluded_training.source_key,
                reason="Test exclusion",
                created_by_user_id=admin.id,
            ),
        ]
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        all_response = await client.get(
            "/api/rag/documents", params={"search": "Exclusion Summary"}
        )
        page_response = await client.get(
            "/api/rag/documents", params={"search": "Exclusion Summary", "types": "website_page"}
        )
        included_response = await client.get(
            "/api/rag/documents", params={"search": "Exclusion Summary", "exclusion": "included"}
        )

    assert all_response.status_code == 200
    assert all_response.json()["excluded"] == {"chunks": 3, "documents": 2, "tokens": 40}

    assert page_response.status_code == 200
    assert page_response.json()["excluded"] == {"chunks": 2, "documents": 1, "tokens": 17}

    assert included_response.status_code == 200
    assert included_response.json()["excluded"] == {"chunks": 0, "documents": 0, "tokens": 0}


@pytest.mark.asyncio
async def test_rag_document_chunks_filters_by_exclusion_status(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-chunk-exclusion-filter",
    )
    included_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9611,
        title="Chunk Exclusion Filter Included",
    )
    excluded_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9612,
        title="Chunk Exclusion Filter Excluded",
    )
    transactional_session.add(
        RagDocumentExclusion(
            source_key=excluded_document.source_key,
            reason="Test exclusion",
            created_by_user_id=admin.id,
        )
    )
    await transactional_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        included_response = await client.get(
            "/api/rag/documents/chunks",
            params={
                "search": "Chunk Exclusion Filter",
                "exclusion": "included",
                "types": "website_page",
            },
        )
        excluded_response = await client.get(
            "/api/rag/documents/chunks",
            params={
                "search": "Chunk Exclusion Filter",
                "exclusion": "excluded",
                "types": "website_page",
            },
        )

    assert included_response.status_code == 200
    included_document_ids = {item["document"]["id"] for item in included_response.json()["items"]}
    assert str(included_document.id) in included_document_ids
    assert str(excluded_document.id) not in included_document_ids

    assert excluded_response.status_code == 200
    excluded_document_ids = {item["document"]["id"] for item in excluded_response.json()["items"]}
    assert str(included_document.id) not in excluded_document_ids
    assert str(excluded_document.id) in excluded_document_ids


@pytest.mark.asyncio
async def test_rag_similarity_search_filters_by_exclusion_status(
    transactional_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _create_user(
        transactional_session,
        group_slug=SystemGroupSlug.ADMIN,
        email_prefix="rag-admin-sim-exclusion-filter",
    )
    included_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9621,
        title="Similarity Exclusion Filter Included",
    )
    excluded_document = await _create_document(
        transactional_session,
        document_type=DocumentType.WEBSITE_PAGE,
        source_id=9622,
        title="Similarity Exclusion Filter Excluded",
    )
    transactional_session.add(
        RagDocumentExclusion(
            source_key=excluded_document.source_key,
            reason="Test exclusion",
            created_by_user_id=admin.id,
        )
    )
    await transactional_session.flush()

    class _FakeEmbeddingData:
        def __init__(self) -> None:
            self.embedding = [0.0] * EMBEDDING_VECTOR_DIMENSIONS

    class _FakeEmbeddingResponse:
        def __init__(self) -> None:
            self.data = [_FakeEmbeddingData()]

    class _FakeEmbeddings:
        async def create(self, **_kwargs: object) -> _FakeEmbeddingResponse:
            return _FakeEmbeddingResponse()

    class _FakeOpenAI:
        embeddings = _FakeEmbeddings()

    monkeypatch.setattr("app.api.routes.rag.get_azure_openai_client", _FakeOpenAI)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        included_response = await client.get(
            "/api/rag/documents/similarity",
            params={
                "query": "Similarity Exclusion Filter",
                "exclusion": "included",
                "types": "website_page",
            },
        )
        excluded_response = await client.get(
            "/api/rag/documents/similarity",
            params={
                "query": "Similarity Exclusion Filter",
                "exclusion": "excluded",
                "types": "website_page",
            },
        )

    assert included_response.status_code == 200
    included_ids = {item["id"] for item in included_response.json()["items"]}
    assert str(included_document.id) in included_ids
    assert str(excluded_document.id) not in included_ids

    assert excluded_response.status_code == 200
    excluded_ids = {item["id"] for item in excluded_response.json()["items"]}
    assert str(included_document.id) not in excluded_ids
    assert str(excluded_document.id) in excluded_ids


@pytest.mark.asyncio
async def test_rag_document_detail_returns_404_for_missing_document(
    transactional_session: AsyncSession,
) -> None:
    admin = await _create_user(
        transactional_session, group_slug=SystemGroupSlug.ADMIN, email_prefix="rag-admin-missing"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        authenticate_client(client, admin.id)
        response = await client.get(f"/api/rag/documents/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "RAG document not found"}
