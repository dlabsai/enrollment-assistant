from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from app.models import DocumentType
from app.rag import build as rag_build

if TYPE_CHECKING:
    from collections.abc import Generator


class FakeSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class SpanRecorder:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    @contextmanager
    def span(self, name: str, **attributes: object) -> Generator[FakeSpan]:
        recorded_span = FakeSpan(name)
        recorded_span.attributes.update(attributes)
        self.spans.append(recorded_span)
        yield recorded_span


class DummySession:
    async def execute(self, *_: object, **__: object) -> None:
        return None

    async def delete(self, *_: object, **__: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_embeddings_batch_uses_stable_span_name_and_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr(rag_build.telemetry, "span", recorder.span)

    captured_request: dict[str, object] = {}

    class FakeEmbeddings:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            captured_request.update(kwargs)
            texts = cast("list[str]", kwargs["input"])
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[float(index)]) for index, _ in enumerate(texts)],
                usage=SimpleNamespace(prompt_tokens=17),
            )

    openai = SimpleNamespace(embeddings=FakeEmbeddings())

    embeddings = await rag_build._create_embeddings_batch(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        asyncio.Semaphore(1), cast(Any, openai), ["title", "chunk"]
    )

    assert embeddings == [[0.0], [1.0]]
    assert captured_request == {
        "input": ["title", "chunk"],
        "model": rag_build.EMBEDDING_MODEL,
        "dimensions": rag_build.EMBEDDING_VECTOR_DIMENSIONS,
    }
    span = recorder.spans[0]
    assert span.name == "rag.create_embeddings_batch"
    assert span.attributes["gen_ai.operation.name"] == "embeddings"
    assert span.attributes["gen_ai.provider.name"] == "azure.ai.openai"
    assert span.attributes["gen_ai.request.model"] == rag_build.EMBEDDING_MODEL
    assert span.attributes["gen_ai.response.model"] == rag_build.EMBEDDING_MODEL
    assert span.attributes["gen_ai.usage.input_tokens"] == 17
    assert span.attributes["app.rag.batch_size"] == 2
    assert span.attributes["app.rag.embedding_dimensions"] == rag_build.EMBEDDING_VECTOR_DIMENSIONS


@pytest.mark.asyncio
async def test_build_search_db_uses_stable_source_span_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr(rag_build.telemetry, "span", recorder.span)
    monkeypatch.setattr(
        rag_build,
        "_get_document_sources",
        lambda: [(list, "Website pages", DocumentType.WEBSITE_PAGE)],
    )

    async def fake_load_existing_documents(*_: object, **__: object) -> dict[int, object]:
        return {}

    monkeypatch.setattr(rag_build, "_load_existing_documents", fake_load_existing_documents)

    await rag_build.build_search_db(
        MagicMock(), cast(Any, DummySession()), force_rebuild=True, dry_run=True
    )

    assert [span.name for span in recorder.spans] == [
        "rag.build_search_db",
        "rag.process_document_source",
    ]
    root_span = recorder.spans[0]
    assert root_span.attributes["app.rag.force_rebuild"] is True
    assert root_span.attributes["app.rag.dry_run"] is True
    assert root_span.attributes["app.rag.rebuild_mode"] == "full_rebuild"
    source_span = recorder.spans[1]
    assert source_span.attributes["app.rag.document_source_name"] == "Website pages"
    assert source_span.attributes["app.rag.document_type"] == "website_page"


@pytest.mark.asyncio
async def test_document_change_spans_use_stable_names_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr(rag_build.telemetry, "span", recorder.span)

    async def fake_process_documents(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(rag_build, "_process_documents", fake_process_documents)

    await rag_build._process_new_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        MagicMock(),
        cast(Any, DummySession()),
        cast(Any, [object(), object()]),
        MagicMock(),
        "Website pages",
    )
    await rag_build._process_deleted_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        cast(Any, DummySession()), cast(Any, [object()]), "Website pages"
    )

    assert [span.name for span in recorder.spans] == [
        "rag.process_new_documents",
        "rag.delete_documents",
    ]
    assert recorder.spans[0].attributes["app.rag.document_count"] == 2
    assert recorder.spans[0].attributes["app.rag.document_type_name"] == "Website pages"
    assert recorder.spans[1].attributes["app.rag.document_count"] == 1
    assert recorder.spans[1].attributes["app.rag.document_type_name"] == "Website pages"


@pytest.mark.asyncio
async def test_process_deleted_documents_flushes_source_key_removals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SpanRecorder()
    monkeypatch.setattr(rag_build.telemetry, "span", recorder.span)
    events: list[str] = []

    class RecordingSession(DummySession):
        async def delete(self, *_: object, **__: object) -> None:
            events.append("delete")

        async def flush(self) -> None:
            events.append("flush")

    await rag_build._process_deleted_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        cast(Any, RecordingSession()), cast(Any, [object()]), "Website pages"
    )

    assert events == ["delete", "flush"]


def test_categorize_documents_uses_timestamps_for_regular_website_pages() -> None:
    source = rag_build.WebsitePage(
        id="10",
        title="Regular Page",
        url="https://demo-university.example.edu/regular",
        markdown_content="same content",
        updated=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    )
    existing = SimpleNamespace(
        id_=10,
        source_key="website_page:10",
        source_updated_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        title="Regular Page",
        url="https://demo-university.example.edu/regular",
        markdown_content="same content",
    )

    categories = rag_build._categorize_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [source], cast(Any, {existing.id_: existing})
    )

    assert categories.changed == [(source, existing)]


def test_categorize_documents_marks_regular_doc_changed_when_sanitized_content_differs() -> None:
    safelink = (
        "https://nam10.safelinks.protection.outlook.com/"
        "?url=https%3A%2F%2Fdemo-university.example.edu%2Fapply%2F&data=abc"
    )
    source = rag_build.WebsitePage(
        id="10",
        title="Regular Page",
        url="https://demo-university.example.edu/regular",
        markdown_content=f"Apply at [Demo University]({safelink})",
        updated=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
    )
    existing = SimpleNamespace(
        id_=10,
        source_key="website_page:10",
        source_updated_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        title="Regular Page",
        url="https://demo-university.example.edu/regular",
        markdown_content=f"Apply at [Demo University]({safelink})",
    )

    categories = rag_build._categorize_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [source], cast(Any, {existing.id_: existing})
    )

    assert categories.changed == [(source, existing)]


def test_categorize_documents_ignores_training_material_mtime_when_content_is_unchanged() -> None:
    source = rag_build.TrainingMaterial(
        id="-505",
        title="Guide",
        url="training-materials://Admissions/Guide.md",
        markdown_content="same Markdown content",
        updated=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        source_path="Admissions/Guide.md",
        file_name="Guide.md",
        file_extension="md",
        content_hash="abc123",
    )
    existing = SimpleNamespace(
        id_=-505,
        source_key="training_material:Admissions/Guide.md",
        source_updated_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        title="Guide",
        url="training-materials://Admissions/Guide.md",
        markdown_content="same Markdown content",
    )

    categories = rag_build._categorize_documents(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [source], cast(Any, {existing.id_: existing})
    )

    assert categories.new == []
    assert categories.changed == []
    assert categories.deleted == []
    assert categories.unchanged == [(source, existing)]


@pytest.mark.asyncio
async def test_prepare_document_data_applies_source_id_overrides() -> None:
    source = rag_build.WebsitePage(
        id="-259925932",
        title="Academic Calendar",
        url="https://demo-university.example.edu/academic-calendar/",
        markdown_content="# Academic Calendar\n",
    )
    text_splitter = rag_build.RecursiveCharacterTextSplitter(
        chunk_size=rag_build.CHUNK_SIZE, chunk_overlap=rag_build.CHUNK_OVERLAP, length_function=len
    )

    [(document_data, _chunks)] = await rag_build._prepare_document_data(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        [source],
        text_splitter,
        "Website pages",
        source_id_overrides={"website_page:-259925932": -76155401},
    )

    assert document_data["id_"] == -76155401


@pytest.mark.asyncio
async def test_incremental_build_deletes_obsolete_docs_before_updates_and_inserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    old_updated = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    new_updated = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    changed_source = rag_build.WebsitePage(
        id="10",
        title="Changed Page",
        url="https://demo-university.example.edu/changed",
        markdown_content="changed",
        updated=new_updated,
    )
    new_source = rag_build.WebsitePage(
        id="20",
        title="New Page",
        url="https://demo-university.example.edu/new",
        markdown_content="new",
    )
    existing_changed = SimpleNamespace(
        id_=10,
        source_key="website_page:10",
        source_updated_at=old_updated,
        title="Changed Page",
        url="https://demo-university.example.edu/changed",
        markdown_content="old content",
    )
    existing_deleted = SimpleNamespace(
        id_=30, source_key="website_page:30", source_updated_at=old_updated
    )

    monkeypatch.setattr(
        rag_build,
        "_get_document_sources",
        lambda: [
            (lambda: [changed_source, new_source], "Website pages", DocumentType.WEBSITE_PAGE)
        ],
    )

    async def fake_load_existing_documents(*_: object, **__: object) -> dict[int, object]:
        return {10: existing_changed, 30: existing_deleted}

    async def fake_process_deleted_documents(*_: object, **__: object) -> None:
        events.append("deleted")

    async def fake_process_changed_documents(*_: object, **__: object) -> None:
        events.append("changed")

    async def fake_process_new_documents(*_: object, **__: object) -> None:
        events.append("new")

    async def fake_refresh_guardrail_url_registries(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(rag_build, "_load_existing_documents", fake_load_existing_documents)
    monkeypatch.setattr(rag_build, "_process_deleted_documents", fake_process_deleted_documents)
    monkeypatch.setattr(rag_build, "_process_changed_documents", fake_process_changed_documents)
    monkeypatch.setattr(rag_build, "_process_new_documents", fake_process_new_documents)
    monkeypatch.setattr(
        rag_build, "refresh_guardrail_url_registries", fake_refresh_guardrail_url_registries
    )

    await rag_build.build_search_db(MagicMock(), cast(Any, DummySession()))

    assert events == ["deleted", "changed", "new"]
