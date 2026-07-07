"""Small local text splitter for RAG document chunking."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence


class RecursiveCharacterTextSplitter:
    """Split text recursively by paragraph, line, word, then character.

    This covers the RAG builder's previous `langchain-text-splitters` use without
    importing LangChain's Pydantic-v1 compatibility layer on Python 3.14.
    """

    def __init__(
        self,
        *,
        chunk_size: int,
        chunk_overlap: int,
        length_function: Callable[[str], int] = len,
        separators: Sequence[str] = ("\n\n", "\n", " ", ""),
        strip_whitespace: bool = True,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap must be >= 0, got {chunk_overlap}")
        if chunk_overlap > chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must not exceed chunk_size ({chunk_size})"
            )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._length_function = length_function
        self._separators = tuple(separators)
        self._strip_whitespace = strip_whitespace

    def split_text(self, text: str) -> list[str]:
        """Return chunks for `text`."""
        if text == "":
            return []
        return self._split_text(text, self._separators)

    def _split_text(self, text: str, separators: Sequence[str]) -> list[str]:
        separator = separators[-1] if separators else ""
        next_separators: Sequence[str] = ()
        for index, candidate in enumerate(separators):
            if candidate == "" or candidate in text:
                separator = candidate
                next_separators = separators[index + 1 :]
                break

        splits = self._split_with_separator(text, separator)
        final_chunks: list[str] = []
        good_splits: list[str] = []

        for split in splits:
            if self._length_function(split) < self._chunk_size:
                good_splits.append(split)
                continue

            if good_splits:
                final_chunks.extend(self._merge_splits(good_splits))
                good_splits = []

            if not next_separators:
                chunk = self._normalize_chunk(split)
                if chunk is not None:
                    final_chunks.append(chunk)
            else:
                final_chunks.extend(self._split_text(split, next_separators))

        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits))

        return final_chunks

    @staticmethod
    def _split_with_separator(text: str, separator: str) -> list[str]:
        if separator == "":
            return list(text)

        pieces = text.split(separator)
        if len(pieces) == 1:
            return [text]

        splits: list[str] = []
        first = pieces[0]
        if first:
            splits.append(first)
        for piece in pieces[1:]:
            if piece:
                splits.append(f"{separator}{piece}")
            else:
                splits.append(separator)
        return [split for split in splits if split]

    def _normalize_chunk(self, chunk: str) -> str | None:
        if self._strip_whitespace:
            chunk = chunk.strip()
        return chunk or None

    def _merge_splits(self, splits: Iterable[str]) -> list[str]:
        docs: list[str] = []
        current_doc: list[str] = []
        total = 0

        for split in splits:
            split_len = self._length_function(split)
            if total + split_len > self._chunk_size and current_doc:
                doc = self._normalize_chunk("".join(current_doc))
                if doc is not None:
                    docs.append(doc)
                while current_doc and (
                    total > self._chunk_overlap or total + split_len > self._chunk_size
                ):
                    total -= self._length_function(current_doc[0])
                    current_doc = current_doc[1:]

            current_doc.append(split)
            total += split_len

        doc = self._normalize_chunk("".join(current_doc))
        if doc is not None:
            docs.append(doc)
        return docs
