import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from jinja2 import Template
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import engine as chat_engine
from app.chat.agents import GuardrailsResult
from app.chat.engine import ModelSettings
from app.chat.url_guardrails import (
    build_allowed_url_registry,
    build_blog_url_feedback,
    build_unknown_url_feedback,
    collect_normalized_urls,
    extract_urls,
    find_blog_urls,
    find_unknown_urls,
    get_allowed_url_registry_for_va,
    get_guardrail_url_registry_key,
    is_blog_url,
    normalize_url,
    refresh_guardrail_url_registries,
)
from app.chat.url_guardrails_config import get_prompt_allowed_urls
from app.core.config import settings
from app.core.db import async_session_factory
from app.models import Document, DocumentType, GuardrailUrlRegistry
from app.rag import build as rag_build
from app.rag.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.rag.source_keys import document_source_key

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


@pytest.fixture
def model_settings() -> ModelSettings:
    return ModelSettings(
        model=settings.GUARDRAIL_MODEL,
        temperature=settings.GUARDRAIL_MODEL_TEMPERATURE,
        max_tokens=settings.GUARDRAIL_MODEL_MAX_TOKENS,
    )


def test_extract_urls_finds_http_relative_mailto_domain_and_email_variants() -> None:
    extracted = extract_urls(
        "Visit https://demo-university.example.edu/admissions/, "
        "demo-university.example.edu/admissions/, /admissions/, "
        "mailto:career@demo-university.example.edu, and career@demo-university.example.edu."
    )

    assert extracted == [
        "https://demo-university.example.edu/admissions/",
        "demo-university.example.edu/admissions/",
        "/admissions/",
        "mailto:career@demo-university.example.edu",
        "career@demo-university.example.edu",
    ]


def test_normalize_url_strips_fragment_slash_and_punctuation() -> None:
    assert (
        normalize_url("https://demo-university.example.edu/admissions/#top),")
        == "https://demo-university.example.edu/admissions"
    )


def test_normalize_url_strips_markdown_emphasis_delimiters() -> None:
    url = "https://www.parchment.com/u/registration/30816782/institution"
    message = f"Order transcripts at **{url}**."
    allowed_urls = frozenset({url})

    assert extract_urls(message) == [url]
    assert normalize_url(f"{url}**") == url
    assert find_unknown_urls(message, allowed_urls=allowed_urls) == []


def test_normalize_url_normalizes_www_demo_hosts() -> None:
    assert (
        normalize_url("https://www.demo-university.example.edu/admissions/")
        == "https://demo-university.example.edu/admissions"
    )
    assert (
        normalize_url(
            "https://www.catalog.demo-university.example.edu/content.php?catoid=7&navoid=274"
        )
        == "https://catalog.demo-university.example.edu/content.php?catoid=7&navoid=274"
    )


def test_normalize_url_supports_scheme_less_relative_mailto_and_bare_email() -> None:
    assert normalize_url("demo-university.example.edu") == "https://demo-university.example.edu/"
    assert (
        normalize_url("demo-university.example.edu/admissions/")
        == "https://demo-university.example.edu/admissions"
    )
    assert normalize_url("/admissions/") == "https://demo-university.example.edu/admissions"
    assert (
        normalize_url("mailto:Career@demo-university.example.edu")
        == "mailto:career@demo-university.example.edu"
    )
    assert (
        normalize_url("Career@demo-university.example.edu")
        == "mailto:career@demo-university.example.edu"
    )


def test_collect_normalized_urls_normalizes_url_like_variants() -> None:
    normalized = collect_normalized_urls(
        "Use demo-university.example.edu/admissions/, /admissions/, "
        "career@demo-university.example.edu, and mailto:career@demo-university.example.edu."
    )

    assert normalized == {
        "https://demo-university.example.edu/admissions",
        "mailto:career@demo-university.example.edu",
    }


def test_find_unknown_urls_deduplicates_unknown_urls() -> None:
    allowed_urls = frozenset({"https://demo-university.example.edu/admissions"})

    unknown_urls = find_unknown_urls(
        "Visit https://demo-university.example.edu/not-real/ and https://demo-university.example.edu/not-real/.",
        allowed_urls=allowed_urls,
    )

    assert unknown_urls == ["https://demo-university.example.edu/not-real"]


def test_find_unknown_urls_catches_scheme_less_relative_mailto_and_bare_email() -> None:
    unknown_urls = find_unknown_urls(
        "Use demo-university.example.edu/not-real/, /also-not-real/, "
        "mailto:unknown@demo-university.example.edu, and unknown@demo-university.example.edu.",
        allowed_urls=frozenset(
            {
                "https://demo-university.example.edu/admissions",
                "mailto:career@demo-university.example.edu",
            }
        ),
    )

    assert unknown_urls == [
        "https://demo-university.example.edu/not-real",
        "https://demo-university.example.edu/also-not-real",
        "mailto:unknown@demo-university.example.edu",
    ]


def test_find_unknown_urls_allows_https_upgrade_from_known_http_url_only() -> None:
    assert (
        find_unknown_urls(
            "Use https://example.edu/path?x=1 for details.",
            allowed_urls=frozenset({"http://example.edu/path?x=1"}),
        )
        == []
    )
    assert find_unknown_urls(
        "Use http://example.edu/path?x=1 for details.",
        allowed_urls=frozenset({"https://example.edu/path?x=1"}),
    ) == ["http://example.edu/path?x=1"]


def test_is_blog_url_blocks_any_path_containing_blog() -> None:
    assert is_blog_url("https://demo-university.example.edu/blog") is True
    assert is_blog_url("https://demo-university.example.edu/blog-2/article") is True
    assert is_blog_url("https://demo-university.example.edu/student-services/blog/article") is True
    assert is_blog_url("https://demo-university.example.edu/admissions") is False


def test_find_blog_urls_deduplicates_blog_urls() -> None:
    blog_urls = find_blog_urls(
        "Visit https://demo-university.example.edu/blog/article, /blog/article/, "
        "and demo-university.example.edu/blog/article#top."
    )

    assert blog_urls == ["https://demo-university.example.edu/blog/article"]


def test_build_unknown_url_feedback_lists_all_unknown_urls() -> None:
    feedback = build_unknown_url_feedback(
        [
            "https://demo-university.example.edu/not-real",
            "https://apply.demo-university.example.edu/unknown",
            "mailto:unknown@demo-university.example.edu",
        ]
    )

    assert "https://demo-university.example.edu/not-real" in feedback
    assert "https://apply.demo-university.example.edu/unknown" in feedback
    assert "mailto:unknown@demo-university.example.edu" in feedback
    assert "Do not invent or guess links, email addresses, or URLs." in feedback


def test_build_blog_url_feedback_lists_all_blog_urls() -> None:
    feedback = build_blog_url_feedback(
        [
            "https://demo-university.example.edu/blog/article",
            "https://demo-university.example.edu/student-services/blog/article",
        ]
    )

    assert "https://demo-university.example.edu/blog/article" in feedback
    assert "https://demo-university.example.edu/student-services/blog/article" in feedback
    assert "disallowed blog URL" in feedback


def test_get_guardrail_url_registry_key_uses_va_scope() -> None:
    assert get_guardrail_url_registry_key(is_internal=True) == "internal_v7"
    assert get_guardrail_url_registry_key(is_internal=False) == "public_v7"


@pytest.mark.asyncio
async def test_build_allowed_url_registry_includes_document_urls_and_content_urls(
    session: AsyncSession,
) -> None:
    document_url = "https://demo-university.example.edu/url-registry-test/"
    content_url = "https://demo-university.example.edu/student-support/"
    markdown_content = f"# URL registry test\n\nUse support at {content_url}."
    document = Document(
        type=DocumentType.WEBSITE_PAGE,
        id_=-12342,
        source_key=document_source_key(
            DocumentType.WEBSITE_PAGE, -12342, "URL registry test", document_url, markdown_content
        ),
        title="URL registry test",
        url=document_url,
        markdown_content=markdown_content,
        token_count=20,
        character_count=len(markdown_content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(document)
    await session.flush()

    registry = await build_allowed_url_registry(session)
    content_urls = extract_urls(markdown_content)

    assert content_urls
    assert normalize_url(document_url) in registry
    assert normalize_url(content_urls[0]) in registry


@pytest.mark.asyncio
async def test_build_allowed_url_registry_allows_external_urls_from_document_content(
    session: AsyncSession,
) -> None:
    document_url = "https://demo-university.example.edu/external-url-registry-test/"
    markdown_content = (
        "# External URL registry test\n\n"
        "Use Federal Student Aid at https://studentaid.gov/h/apply-for-aid/fafsa/."
    )
    document = Document(
        type=DocumentType.WEBSITE_PAGE,
        id_=-12344,
        source_key=document_source_key(
            DocumentType.WEBSITE_PAGE,
            -12344,
            "External URL registry test",
            document_url,
            markdown_content,
        ),
        title="External URL registry test",
        url=document_url,
        markdown_content=markdown_content,
        token_count=20,
        character_count=len(markdown_content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(document)
    await session.flush()

    registry = await build_allowed_url_registry(session, is_internal=False)

    assert "https://studentaid.gov/h/apply-for-aid/fafsa" in registry
    assert (
        find_unknown_urls(
            "Complete the FAFSA at https://studentaid.gov/h/apply-for-aid/fafsa.",
            allowed_urls=registry,
        )
        == []
    )


@pytest.mark.asyncio
async def test_build_allowed_url_registry_allows_https_responses_for_http_source_urls(
    session: AsyncSession,
) -> None:
    document_url = "http://demo-university.example.edu/http-url-registry-test/"
    markdown_content = (
        "# HTTP URL registry test\n\n"
        "Use this external HTTP link: http://example.edu/legacy-path/?ref=rag."
    )
    document = Document(
        type=DocumentType.WEBSITE_PAGE,
        id_=-12343,
        source_key=document_source_key(
            DocumentType.WEBSITE_PAGE,
            -12343,
            "HTTP URL registry test",
            document_url,
            markdown_content,
        ),
        title="HTTP URL registry test",
        url=document_url,
        markdown_content=markdown_content,
        token_count=20,
        character_count=len(markdown_content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(document)
    await session.flush()

    registry = await build_allowed_url_registry(session, is_internal=False)

    assert "http://demo-university.example.edu/http-url-registry-test" in registry
    assert "http://example.edu/legacy-path?ref=rag" in registry
    assert (
        find_unknown_urls(
            "Use https://demo-university.example.edu/http-url-registry-test for details.",
            allowed_urls=registry,
        )
        == []
    )
    assert (
        find_unknown_urls(
            "Use https://example.edu/legacy-path?ref=rag for details.", allowed_urls=registry
        )
        == []
    )


@pytest.mark.asyncio
async def test_build_allowed_url_registry_excludes_training_material_urls_for_public_scope(
    session: AsyncSession,
) -> None:
    document_url = "training-materials://internal-admissions-training.pdf"
    markdown_content = (
        "# Internal admissions training\n\n"
        "Internal training material: https://demo-university.example.edu/internal/training-materials/internal-only\n"
        "Internal email: internal.training@demo-university.example.edu"
    )
    training_material = Document(
        type=DocumentType.TRAINING_MATERIAL,
        id_=-12345,
        source_key=document_source_key(
            DocumentType.TRAINING_MATERIAL,
            -12345,
            "Internal admissions training",
            document_url,
            markdown_content,
        ),
        title="Internal admissions training",
        url=document_url,
        markdown_content=markdown_content,
        token_count=10,
        character_count=140,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(training_material)
    await session.flush()

    registry = await build_allowed_url_registry(session, is_internal=False)

    assert (
        "https://demo-university.example.edu/internal/training-materials/internal-only"
        not in registry
    )
    assert "mailto:internal.training@demo-university.example.edu" not in registry


@pytest.mark.asyncio
async def test_build_allowed_url_registry_includes_training_material_urls_for_internal_scope(
    session: AsyncSession,
) -> None:
    document_url = "training-materials://internal-admissions-training-internal.pdf"
    markdown_content = (
        "# Internal admissions training\n\n"
        "Internal training material: https://demo-university.example.edu/internal/training-materials/internal-allowed\n"
        "Internal email: internal.allowed@demo-university.example.edu"
    )
    training_material = Document(
        type=DocumentType.TRAINING_MATERIAL,
        id_=-12346,
        source_key=document_source_key(
            DocumentType.TRAINING_MATERIAL,
            -12346,
            "Internal admissions training internal",
            document_url,
            markdown_content,
        ),
        title="Internal admissions training internal",
        url=document_url,
        markdown_content=markdown_content,
        token_count=10,
        character_count=140,
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(training_material)
    await session.flush()

    registry = await build_allowed_url_registry(session, is_internal=True)

    assert (
        "https://demo-university.example.edu/internal/training-materials/internal-allowed"
        in registry
    )
    assert (
        "https://demo-university.example.edu/internal/training-materials/"
        "internal-admissions-training-internal.pdf"
    ) in registry
    assert "mailto:internal.allowed@demo-university.example.edu" in registry


@pytest.mark.asyncio
async def test_build_allowed_url_registry_includes_extra_urls(session: AsyncSession) -> None:
    registry = await build_allowed_url_registry(
        session,
        extra_urls=[
            "https://apply.demo-university.example.edu/",
            "/admissions/",
            "career@demo-university.example.edu",
            "mailto:mgary@demo-university.example.edu",
        ],
    )

    assert "https://apply.demo-university.example.edu/" in registry
    assert "https://demo-university.example.edu/admissions" in registry
    assert "mailto:career@demo-university.example.edu" in registry
    assert "mailto:mgary@demo-university.example.edu" in registry


@pytest.mark.asyncio
async def test_build_allowed_url_registry_includes_indexed_catalog_urls(
    session: AsyncSession,
) -> None:
    document_url = "https://catalog.demo-university.example.edu/preview_course.php?catoid=88&coid=3"
    markdown_content = (
        "# ACC 101 - Accounting\n\n"
        "See the program at "
        "https://catalog.demo-university.example.edu/preview_program.php?catoid=88&poid=2."
    )
    document = Document(
        type=DocumentType.CATALOG_COURSE,
        id_=-12347,
        source_key=document_source_key(
            DocumentType.CATALOG_COURSE,
            -12347,
            "ACC 101 - Accounting",
            document_url,
            markdown_content,
        ),
        title="ACC 101 - Accounting",
        url=document_url,
        markdown_content=markdown_content,
        token_count=20,
        character_count=len(markdown_content),
        title_embedding=[0.0] * EMBEDDING_VECTOR_DIMENSIONS,
    )
    session.add(document)
    await session.flush()

    registry = await build_allowed_url_registry(session, is_internal=False)

    assert document_url in registry
    assert (
        "https://catalog.demo-university.example.edu/preview_program.php?catoid=88&poid=2"
        in registry
    )


def test_get_prompt_allowed_urls_returns_curated_prompt_urls() -> None:
    assert get_prompt_allowed_urls(is_internal=True) == (
        "https://apply.demo-university.example.edu/",
        "https://demo-university.example.edu/accreditation-and-consumer-information/",
        "https://catalog.demo-university.example.edu/",
        "https://studentaid.gov",
        "https://www.bls.gov/ooh/",
    )
    assert get_prompt_allowed_urls(is_internal=False) == (
        "https://apply.demo-university.example.edu/",
        "https://demo-university.example.edu/accreditation-and-consumer-information/",
        "https://catalog.demo-university.example.edu/",
        "https://studentaid.gov",
        "https://www.bls.gov/ooh/",
    )


@pytest.mark.asyncio
async def test_get_allowed_url_registry_for_va_persists_missing_registry(
    session: AsyncSession,
) -> None:
    key = get_guardrail_url_registry_key(is_internal=True)
    existing = (
        await session.execute(select(GuardrailUrlRegistry).where(GuardrailUrlRegistry.key == key))
    ).scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    registry = await get_allowed_url_registry_for_va(session, is_internal=True)

    persisted = (
        await session.execute(select(GuardrailUrlRegistry).where(GuardrailUrlRegistry.key == key))
    ).scalar_one()

    assert registry == frozenset(persisted.urls)
    assert "https://apply.demo-university.example.edu/" in registry
    assert "https://www.bls.gov/ooh" in registry
    assert "https://demo-university.example.edu/accreditation-and-consumer-information" in registry
    assert "https://studentaid.gov/" in registry


@pytest.mark.asyncio
async def test_get_allowed_url_registry_for_va_uses_persisted_registry(
    session: AsyncSession,
) -> None:
    key = get_guardrail_url_registry_key(is_internal=True)
    existing = (
        await session.execute(select(GuardrailUrlRegistry).where(GuardrailUrlRegistry.key == key))
    ).scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    persisted = GuardrailUrlRegistry(
        key=key, urls=["https://demo-university.example.edu/custom-persisted-url"]
    )
    session.add(persisted)
    await session.flush()

    registry = await get_allowed_url_registry_for_va(session, is_internal=True)

    assert registry == frozenset({"https://demo-university.example.edu/custom-persisted-url"})


@pytest.mark.asyncio
async def test_get_allowed_url_registry_for_va_concurrent_cold_start_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "test_concurrent_guardrail_registry"
    expected_urls = frozenset({"https://demo-university.example.edu/concurrency-test"})

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(
                delete(GuardrailUrlRegistry).where(GuardrailUrlRegistry.key == key)
            )
            await session.commit()

    async def fake_build_allowed_url_registry(
        session: AsyncSession, *, extra_urls: Any = (), is_internal: bool = True
    ) -> frozenset[str]:
        del session, extra_urls, is_internal
        await asyncio.sleep(0.05)
        return expected_urls

    def fake_get_guardrail_url_registry_key(*, is_internal: bool) -> str:
        del is_internal
        return key

    monkeypatch.setattr(
        "app.chat.url_guardrails.get_guardrail_url_registry_key",
        fake_get_guardrail_url_registry_key,
    )
    monkeypatch.setattr(
        "app.chat.url_guardrails.build_allowed_url_registry", fake_build_allowed_url_registry
    )

    await cleanup()

    try:

        async def load_registry_once() -> frozenset[str]:
            async with async_session_factory() as session:
                registry = await get_allowed_url_registry_for_va(session, is_internal=True)
                await session.commit()
                return registry

        registries = await asyncio.gather(load_registry_once(), load_registry_once())

        assert registries == [expected_urls, expected_urls]

        async with async_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GuardrailUrlRegistry).where(GuardrailUrlRegistry.key == key)
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert rows[0].urls == sorted(expected_urls)
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_refresh_guardrail_url_registries_populates_all_variants(
    session: AsyncSession,
) -> None:
    existing_rows = (await session.execute(select(GuardrailUrlRegistry))).scalars().all()
    for row in existing_rows:
        await session.delete(row)
    await session.flush()

    await refresh_guardrail_url_registries(session)

    rows = (
        await session.execute(select(GuardrailUrlRegistry.key, GuardrailUrlRegistry.urls))
    ).all()
    keys = {row[0] for row in rows}

    assert keys == {"internal_v7", "public_v7"}


@pytest.mark.asyncio
async def test_build_allowed_url_registry_allows_extra_catalog_urls(session: AsyncSession) -> None:
    registry = await build_allowed_url_registry(
        session,
        extra_urls=[
            "https://catalog.demo-university.example.edu/content.php?catoid=7&navoid=274",
            "catalog.demo-university.example.edu/content.php?catoid=7&navoid=274",
            "https://catalog.demo-university.example.edu/",
            "https://apply.demo-university.example.edu/",
        ],
    )

    assert "https://catalog.demo-university.example.edu/content.php?catoid=7&navoid=274" in registry
    assert "https://catalog.demo-university.example.edu/" in registry
    assert "https://apply.demo-university.example.edu/" in registry


@pytest.mark.asyncio
async def test_build_allowed_url_registry_excludes_blog_urls_even_if_present(
    session: AsyncSession,
) -> None:
    registry = await build_allowed_url_registry(
        session,
        extra_urls=[
            "https://demo-university.example.edu/admissions/",
            "/admissions/",
            "https://demo-university.example.edu/blog/article/",
            "/blog/article/",
        ],
    )

    assert "https://demo-university.example.edu/admissions" in registry
    assert "https://demo-university.example.edu/blog/article" not in registry


@pytest.mark.asyncio
async def test_build_search_db_refreshes_guardrail_registries_for_direct_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class DummySession:
        async def commit(self) -> None:
            events.append("commit")

    @asynccontextmanager
    async def fake_get_session() -> AsyncGenerator[DummySession]:
        yield DummySession()

    async def fake_refresh_guardrail_url_registries(session: DummySession) -> None:
        assert isinstance(session, DummySession)
        events.append("refresh")

    monkeypatch.setattr(rag_build, "get_session", fake_get_session)
    monkeypatch.setattr(rag_build, "_get_document_sources", list)
    monkeypatch.setattr(
        rag_build, "refresh_guardrail_url_registries", fake_refresh_guardrail_url_registries
    )

    await rag_build.build_search_db(MagicMock(), cast(Any, DummySession()), dry_run=False)

    assert events == ["refresh", "commit"]


@pytest.mark.asyncio
async def test_run_guardrails_merges_llm_and_url_feedback(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings
) -> None:
    async def fake_run_agent(*args: Any, **kwargs: Any) -> tuple[SimpleNamespace, float]:
        return (
            SimpleNamespace(
                output=GuardrailsResult(is_valid=False, feedback="LLM judge feedback.")
            ),
            0.25,
        )

    monkeypatch.setattr(chat_engine, "run_agent", fake_run_agent)

    run_guardrails = getattr(chat_engine, "_run_guardrails")
    is_valid, feedback, guardrails_log, duration = await run_guardrails(
        model_settings,
        [],
        "See /definitely-not-real/ and unknown@demo-university.example.edu for more details.",
        template=Template("{{ chatbot_agent_response }}"),
        allowed_url_registry=frozenset(
            {"https://demo-university.example.edu/accreditation-and-consumer-information"}
        ),
    )

    assert is_valid is False
    assert "LLM judge feedback." in feedback
    assert "https://demo-university.example.edu/definitely-not-real" in feedback
    assert "mailto:unknown@demo-university.example.edu" in feedback
    assert guardrails_log == [
        {
            "assistant_message": (
                "See /definitely-not-real/ and unknown@demo-university.example.edu "
                "for more details."
            ),
            "guardrails_message": feedback,
        }
    ]
    assert duration == 0.25


@pytest.mark.asyncio
async def test_run_guardrails_passes_same_turn_retry_context(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings
) -> None:
    captured_deps: Any = None
    captured_system_prompt: str | None = None

    async def fake_run_agent(*args: Any, **kwargs: Any) -> tuple[SimpleNamespace, float]:
        nonlocal captured_deps, captured_system_prompt
        captured_deps = kwargs["deps"]
        captured_system_prompt = kwargs["system_prompt"]
        return (SimpleNamespace(output=GuardrailsResult(is_valid=True, feedback=None)), 0.1)

    monkeypatch.setattr(chat_engine, "run_agent", fake_run_agent)

    previous_attempts = [
        {
            "assistant_message": "First rejected answer with $100.",
            "guardrails_message": "Remove the dollar amount.",
        },
        {
            "assistant_message": "Second rejected answer with /missing-link/.",
            "guardrails_message": "Remove the unknown link.",
        },
    ]
    template = Template(
        "user={{ current_user_message }}\n"
        "previous={{ previous_rejected_attempts | length }}\n"
        "first={{ previous_rejected_attempts[0].assistant_message }}\n"
        "first_feedback={{ previous_rejected_attempts[0].guardrails_message }}\n"
        "candidate={{ chatbot_agent_response }}"
    )

    run_guardrails = getattr(chat_engine, "_run_guardrails")
    is_valid, feedback, guardrails_log, _duration = await run_guardrails(
        model_settings,
        previous_attempts,
        "Current candidate answer.",
        current_user_message="Current user question?",
        template=template,
    )

    assert is_valid is True
    assert feedback == ""
    assert guardrails_log == previous_attempts
    assert captured_deps.response_to_check == "Current candidate answer."
    assert captured_deps.current_user_message == "Current user question?"
    assert captured_deps.previous_rejected_attempts == previous_attempts
    assert captured_system_prompt == (
        "user=Current user question?\n"
        "previous=2\n"
        "first=First rejected answer with $100.\n"
        "first_feedback=Remove the dollar amount.\n"
        "candidate=Current candidate answer."
    )


@pytest.mark.asyncio
async def test_run_guardrails_traces_url_guardrail_decision(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings
) -> None:
    class FakeSpan:
        def __init__(self) -> None:
            self.attributes: dict[str, object] = {}

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes[key] = value

    spans: list[tuple[str, FakeSpan]] = []

    @contextmanager
    def fake_span(name: str, **_: object) -> Generator[FakeSpan]:
        span = FakeSpan()
        spans.append((name, span))
        yield span

    async def fake_run_agent(*args: Any, **kwargs: Any) -> tuple[SimpleNamespace, float]:
        return (SimpleNamespace(output=GuardrailsResult(is_valid=True, feedback=None)), 0.1)

    monkeypatch.setattr(chat_engine, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_engine.telemetry, "span", fake_span)

    run_guardrails = getattr(chat_engine, "_run_guardrails")
    is_valid, feedback, _guardrails_log, _duration = await run_guardrails(
        model_settings,
        [],
        "Use /blog/article/ and /definitely-not-real/.",
        template=Template("{{ chatbot_agent_response }}"),
        allowed_url_registry=frozenset({"https://demo-university.example.edu/admissions"}),
    )

    assert is_valid is False
    assert "https://demo-university.example.edu/blog/article" in feedback
    assert "https://demo-university.example.edu/definitely-not-real" in feedback
    assert len(spans) == 1
    span_name, span = spans[0]
    assert span_name == "url_guardrails"
    assert "app.guardrails.url.allowed_count" not in span.attributes
    assert span.attributes["app.guardrails.url.is_valid"] is False
    assert (
        span.attributes["app.guardrails.url.blog_urls"]
        == '["https://demo-university.example.edu/blog/article"]'
    )
    assert span.attributes["app.guardrails.url.unknown_urls"] == (
        '["https://demo-university.example.edu/definitely-not-real"]'
    )


@pytest.mark.asyncio
async def test_run_guardrails_accepts_known_urls_when_llm_accepts(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings
) -> None:
    async def fake_run_agent(*args: Any, **kwargs: Any) -> tuple[SimpleNamespace, float]:
        return (SimpleNamespace(output=GuardrailsResult(is_valid=True, feedback=None)), 0.1)

    monkeypatch.setattr(chat_engine, "run_agent", fake_run_agent)

    run_guardrails = getattr(chat_engine, "_run_guardrails")
    is_valid, feedback, guardrails_log, _duration = await run_guardrails(
        model_settings,
        [],
        "Use demo-university.example.edu/accreditation-and-consumer-information/, "
        "career@demo-university.example.edu, or /admissions/.",
        template=Template("{{ chatbot_agent_response }}"),
        allowed_url_registry=frozenset(
            {
                "https://demo-university.example.edu/accreditation-and-consumer-information",
                "mailto:career@demo-university.example.edu",
                "https://demo-university.example.edu/admissions",
            }
        ),
    )

    assert is_valid is True
    assert feedback == ""
    assert guardrails_log == []


@pytest.mark.asyncio
async def test_run_guardrails_rejects_blog_urls_even_if_known(
    monkeypatch: pytest.MonkeyPatch, model_settings: ModelSettings
) -> None:
    async def fake_run_agent(*args: Any, **kwargs: Any) -> tuple[SimpleNamespace, float]:
        return (SimpleNamespace(output=GuardrailsResult(is_valid=True, feedback=None)), 0.1)

    monkeypatch.setattr(chat_engine, "run_agent", fake_run_agent)

    run_guardrails = getattr(chat_engine, "_run_guardrails")
    is_valid, feedback, guardrails_log, _duration = await run_guardrails(
        model_settings,
        [],
        "Use /blog/article/.",
        template=Template("{{ chatbot_agent_response }}"),
        allowed_url_registry=frozenset({"https://demo-university.example.edu/blog/article"}),
    )

    assert is_valid is False
    assert "disallowed blog URL" in feedback
    assert "https://demo-university.example.edu/blog/article" in feedback
    assert guardrails_log == [
        {"assistant_message": "Use /blog/article/.", "guardrails_message": feedback}
    ]
