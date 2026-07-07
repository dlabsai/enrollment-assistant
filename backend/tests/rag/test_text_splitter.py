from __future__ import annotations

from app.rag.text_splitter import RecursiveCharacterTextSplitter


def test_recursive_character_text_splitter_chunks_with_overlap() -> None:
    splitter = RecursiveCharacterTextSplitter(chunk_size=12, chunk_overlap=4)

    chunks = splitter.split_text("alpha beta gamma delta")

    assert chunks == ["alpha beta", "gamma delta"]
    assert all(len(chunk) <= 12 for chunk in chunks)


def test_recursive_character_text_splitter_splits_long_words_by_character() -> None:
    splitter = RecursiveCharacterTextSplitter(chunk_size=5, chunk_overlap=2)

    chunks = splitter.split_text("abcdefghij")

    assert chunks == ["abcde", "defgh", "ghij"]
    assert all(len(chunk) <= 5 for chunk in chunks)


def test_recursive_character_text_splitter_strips_chunk_whitespace() -> None:
    splitter = RecursiveCharacterTextSplitter(chunk_size=6, chunk_overlap=0)

    assert splitter.split_text("\n\nalpha\n\n\n\nbeta\n\n") == ["alpha", "beta"]
