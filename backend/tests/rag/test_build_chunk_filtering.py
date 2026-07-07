# pyright: reportPrivateUsage=false
from __future__ import annotations

from urllib.parse import quote

import pytest

from app.rag import build as rag_build


def _safelink(target: str) -> str:
    return (
        "https://nam10.safelinks.protection.outlook.com/"
        f"?url={quote(target, safe='')}&data=abc&amp;reserved=0"
    )


def test_indexable_chunk_rejects_punctuation_only_chunks() -> None:
    assert not rag_build._is_indexable_chunk("---")  # noqa: SLF001
    assert not rag_build._is_indexable_chunk(".")  # noqa: SLF001


def test_indexable_chunk_rejects_single_missing_only_markdown_table_row() -> None:
    chunk = "| NaN | NaN | NaT | NaN |"

    assert not rag_build._is_indexable_chunk(chunk)  # noqa: SLF001


def test_indexable_chunk_rejects_multiple_missing_only_markdown_table_rows() -> None:
    chunk = """| NaN | NaN | NaT |
| --- | --- | --- |
| nan |  | nat |"""

    assert not rag_build._is_indexable_chunk(chunk)  # noqa: SLF001


def test_indexable_chunk_keeps_table_rows_with_real_values() -> None:
    chunk = """| Program | Credits | Notes |
| --- | ---: | --- |
| MBA | 36 | NaN |"""

    assert rag_build._is_indexable_chunk(chunk)  # noqa: SLF001


def test_indexable_chunk_keeps_heading_plus_missing_table_rows() -> None:
    chunk = """# Plan of Study
| NaN | NaT | |"""

    assert rag_build._is_indexable_chunk(chunk)  # noqa: SLF001


def test_indexable_chunk_keeps_non_table_text_that_mentions_nan() -> None:
    assert rag_build._is_indexable_chunk("The import produced NaN values in the worksheet.")  # noqa: SLF001


def test_sanitize_rag_markdown_unwraps_outlook_safelinks() -> None:
    safelink = _safelink(
        "https://demo-university.example.edu/financial-aid/scholarships/?q=student%20aid"
    )
    markdown = f"Visit [scholarships]({safelink})."

    assert rag_build._sanitize_rag_markdown_content(markdown) == (  # noqa: SLF001
        "Visit [scholarships](https://demo-university.example.edu/financial-aid/scholarships/?q=student%20aid)."
    )


def test_sanitize_rag_markdown_recursively_unwraps_nested_outlook_safelinks() -> None:
    nested_safelink = _safelink(_safelink("https://demo-university.example.edu/student-services/"))

    assert rag_build._sanitize_rag_markdown_content(nested_safelink) == (  # noqa: SLF001
        "https://demo-university.example.edu/student-services/"
    )


def test_sanitize_rag_markdown_keeps_unparseable_outlook_safelinks() -> None:
    safelink_without_target = "https://nam10.safelinks.protection.outlook.com/?data=abc"
    sanitized = rag_build._sanitize_rag_markdown_content(  # noqa: SLF001
        safelink_without_target
    )

    assert sanitized == safelink_without_target


@pytest.mark.asyncio
async def test_prepare_document_data_stores_sanitized_safelinks_in_chunks() -> None:
    safelink = _safelink("https://demo-university.example.edu/apply/")
    source = rag_build.CatalogPage(
        id="101",
        title="Apply",
        url="https://catalog.demo-university.example.edu/apply",
        markdown_content=f"Apply at [Demo University]({safelink})",
    )
    text_splitter = rag_build.RecursiveCharacterTextSplitter(
        chunk_size=rag_build.CHUNK_SIZE, chunk_overlap=rag_build.CHUNK_OVERLAP, length_function=len
    )

    [(document_data, chunks)] = await rag_build._prepare_document_data(  # noqa: SLF001
        [source], text_splitter, "catalog pages"
    )

    assert (
        document_data["markdown_content"]
        == "Apply at [Demo University](https://demo-university.example.edu/apply/)"
    )
    assert chunks[0][1] == "Apply at [Demo University](https://demo-university.example.edu/apply/)"
