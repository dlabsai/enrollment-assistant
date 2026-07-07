import html
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, PageElement, Tag
from markdownify import markdownify  # pyright: ignore[reportUnknownVariableType]
from rich.logging import RichHandler

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
_NO_SPACE_BEFORE_CHARS = frozenset(".,;:!?)]}…")
_NO_SPACE_AFTER_CHARS = frozenset("([{")
_FORMAT_TAG_NAMES = frozenset({"strong", "b", "em", "i"})
_PDF_FRAGMENT_MIN_ALNUM_CHARS = 8
_PDF_FRAGMENT_MIN_VISIBLE_CHARS = 8
_PDF_FRAGMENT_MIN_ALNUM_RATIO = 0.45
_PDF_LETTER_SPACED_MIN_ALNUM_TOKENS = 4
_PDF_LETTER_SPACED_MIN_ALPHA_TOKENS = 3
_PDF_MULTI_SPACE_RE = re.compile(r" {2,}")
_PDF_SPACE_BEFORE_PUNCTUATION_RE = re.compile(rf"\s+([{re.escape('.,;:!?)]}…')}])")
_PDF_MISSING_SENTENCE_SPACE_RE = re.compile(r"([a-z0-9][.!?])(?=[A-Z])")


def configure_observability() -> None:
    """Configure RAG-script observability hooks."""


def configure_logging(*, level: int = logging.INFO, rich: bool = True) -> None:
    if rich:
        rich_handler = RichHandler(rich_tracebacks=True, markup=True, show_time=True)
        logging.basicConfig(level=level, format="%(message)s", handlers=[rich_handler])
    else:
        logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def normalize_unicode_whitespace(text: str) -> str:
    zero_width_space = "\u200b"
    non_breaking_space = "\u00a0"
    return text.replace(zero_width_space, "").replace(non_breaking_space, " ")


def normalize_html_entities(text: str) -> str:
    return html.unescape(text)


def normalize_text(text: str) -> str:
    return normalize_unicode_whitespace(normalize_html_entities(text))


def _is_pdf_character_fragment_line(line: str) -> bool:
    return len(line) == 1


def _should_collapse_pdf_character_run(lines: list[str]) -> bool:
    visible_chars = [line.strip() for line in lines if line.strip()]
    if not visible_chars:
        return False

    visible_char_count = sum(len(value) for value in visible_chars)
    alnum_count = sum(char.isalnum() for value in visible_chars for char in value)
    return (
        visible_char_count >= _PDF_FRAGMENT_MIN_VISIBLE_CHARS
        and alnum_count >= _PDF_FRAGMENT_MIN_ALNUM_CHARS
        and alnum_count / visible_char_count >= _PDF_FRAGMENT_MIN_ALNUM_RATIO
    )


def _collapse_pdf_character_run(lines: list[str]) -> str:
    has_empty_separator = any(line == "" for line in lines)
    has_literal_space_glyph = any(line != "" and line.strip() == "" for line in lines)
    if has_empty_separator and not has_literal_space_glyph:
        return ""
    if has_empty_separator:
        collapsed = "".join(
            " " if line.strip() == "" else line.strip() for line in lines if line != ""
        )
    else:
        collapsed = "".join(lines)
    collapsed = " ".join(collapsed.split())
    collapsed = _PDF_SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", collapsed)
    return _PDF_MISSING_SENTENCE_SPACE_RE.sub(r"\1 ", collapsed)


def _looks_like_pdf_letter_spaced_line(line: str) -> bool:
    stripped = line.strip()
    if stripped == "" or "|" in stripped:
        return False

    tokens = stripped.split()
    if len(tokens) < _PDF_LETTER_SPACED_MIN_ALNUM_TOKENS:
        return False
    if any(len(token) != 1 for token in tokens):
        return False

    alnum_count = sum(token.isalnum() for token in tokens)
    alpha_count = sum(token.isalpha() for token in tokens)
    return (
        alnum_count >= _PDF_LETTER_SPACED_MIN_ALNUM_TOKENS
        and alpha_count >= _PDF_LETTER_SPACED_MIN_ALPHA_TOKENS
    )


def _collapse_pdf_letter_spaced_group(group: str) -> str:
    result = ""
    needs_space = False
    for token in group.split():
        if token in _NO_SPACE_BEFORE_CHARS:
            result = result.rstrip() + token
            needs_space = token in {":", ";", ".", "!", "?"}
            continue
        if token in _NO_SPACE_AFTER_CHARS:
            if result and not result.endswith(" "):
                result += " "
            result += token
            needs_space = False
            continue
        if needs_space:
            result += " "
            needs_space = False
        result += token
    return result


def _normalize_pdf_letter_spaced_line(line: str) -> str:
    if not _looks_like_pdf_letter_spaced_line(line):
        return line
    groups = _PDF_MULTI_SPACE_RE.split(line.strip())
    return " ".join(_collapse_pdf_letter_spaced_group(group) for group in groups if group)


def normalize_pdf_extracted_text(text: str) -> str:
    r"""Collapse PDF text-extraction artifacts where each glyph became its own line.

    Some PDFs expose individual glyphs to extraction libraries. The raw text then looks like
    ``A\nl\nl\n \no\nf`` or ``G E T T I N G  S T A R T E D``, which creates huge token
    counts and useless chunks. This normalizer is intentionally PDF-scoped and conservative:
    it collapses long runs of one-character lines, collapses letter-spaced headings, removes
    long blank-separated vertical labels, and leaves short numbered/list fragments alone.
    """
    normalized = normalize_unicode_whitespace(text).replace("\r\n", "\n").replace("\r", "\n")
    output_lines: list[str] = []
    character_run: list[str] = []

    def flush_character_run() -> None:
        if not character_run:
            return
        if _should_collapse_pdf_character_run(character_run):
            collapsed = _normalize_pdf_letter_spaced_line(
                _collapse_pdf_character_run(character_run)
            )
            if collapsed != "":
                output_lines.append(collapsed)
        else:
            output_lines.extend(_normalize_pdf_letter_spaced_line(line) for line in character_run)
        character_run.clear()

    for line in normalized.splitlines():
        if _is_pdf_character_fragment_line(line) or (line == "" and character_run):
            character_run.append(line)
            continue
        flush_character_run()
        output_lines.append(_normalize_pdf_letter_spaced_line(line))

    flush_character_run()
    result = "\n".join(output_lines)
    if normalized.endswith("\n"):
        result += "\n"
    return result


def _normalized_node_text(value: PageElement) -> str:
    if isinstance(value, NavigableString):
        return normalize_unicode_whitespace(str(value))
    if isinstance(value, Tag):
        return normalize_unicode_whitespace(value.get_text())
    return ""


def _has_nonblank_text(value: PageElement) -> bool:
    return _normalized_node_text(value).strip() != ""


def _stripped_node_text(value: PageElement) -> str:
    return _normalized_node_text(value).strip()


def _first_visible_char(value: PageElement) -> str:
    text = _stripped_node_text(value)
    return text[:1]


def _last_visible_char(value: PageElement) -> str:
    text = _stripped_node_text(value)
    return text[-1:]


def _is_textless_rendered_tag(value: PageElement) -> bool:
    if not isinstance(value, Tag) or value.name == "br":
        return False
    return _stripped_node_text(value) == ""


def _is_separator_candidate(value: PageElement) -> bool:
    if _is_textless_rendered_tag(value):
        return True
    text = _stripped_node_text(value)
    return len(text) > 1


def _has_leading_whitespace(value: PageElement) -> bool:
    if not isinstance(value, NavigableString):
        return False
    text = _normalized_node_text(value)
    return text != "" and text[:1].isspace()


def _has_trailing_whitespace(value: PageElement) -> bool:
    if not isinstance(value, NavigableString):
        return False
    text = _normalized_node_text(value)
    return text != "" and text[-1:].isspace()


def _needs_space_between(left: PageElement, right: PageElement) -> bool:
    if _has_trailing_whitespace(left) or _has_leading_whitespace(right):
        return False

    if not (_has_nonblank_text(left) or _is_textless_rendered_tag(left)):
        return False
    if not (_has_nonblank_text(right) or _is_textless_rendered_tag(right)):
        return False

    left_char = _last_visible_char(left)
    right_char = _first_visible_char(right)
    if left_char in _NO_SPACE_AFTER_CHARS or right_char in _NO_SPACE_BEFORE_CHARS:
        return False

    return _is_separator_candidate(left) and _is_separator_candidate(right)


def _is_whitespace_only_text_container(value: PageElement) -> bool:
    text = _normalized_node_text(value)
    return text != "" and text.strip() == ""


def _nearest_sibling_has_nonblank_text(value: PageElement | None, *, previous: bool) -> bool:
    while value is not None:
        if _has_nonblank_text(value):
            return True
        if not _is_whitespace_only_text_container(value):
            return False
        value = value.previous_sibling if previous else value.next_sibling
    return False


def _is_empty_format_tag(tag: Tag) -> bool:
    return tag.name in _FORMAT_TAG_NAMES and not tag.contents


def _next_adjacent_format_tag(tag: Tag) -> tuple[list[NavigableString], Tag | None]:
    separator_nodes: list[NavigableString] = []
    sibling = tag.next_sibling
    while isinstance(sibling, NavigableString) and _is_whitespace_only_text_container(sibling):
        separator_nodes.append(sibling)
        sibling = sibling.next_sibling

    if isinstance(sibling, Tag) and sibling.name == tag.name:
        return separator_nodes, sibling
    return [], None


def _needs_space_between_merged_format_tags(
    left: Tag, right: Tag, *, has_source_separator: bool
) -> bool:
    right_text = _stripped_node_text(right)
    if has_source_separator:
        return right_text[:1] not in _NO_SPACE_BEFORE_CHARS

    left_text = _stripped_node_text(left)
    if left_text and right_text:
        left_char = left_text[-1]
        right_char = right_text[0]
        if right_char in _NO_SPACE_BEFORE_CHARS:
            return False
        if left_char.isalpha() and right_char.islower():
            return False
        if len(left_text) == 1 and right_char.isalnum():
            return False

    return _needs_space_between(left, right)


def _merge_adjacent_format_tags(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all(name=_FORMAT_TAG_NAMES)):
        if isinstance(tag, Tag) and _is_empty_format_tag(tag):
            tag.decompose()

    for tag in list(soup.find_all(name=_FORMAT_TAG_NAMES)):
        if not isinstance(tag, Tag) or tag.parent is None:
            continue

        while True:
            separator_nodes, next_tag = _next_adjacent_format_tag(tag)
            if next_tag is None:
                break

            separator = (
                " "
                if _needs_space_between_merged_format_tags(
                    tag, next_tag, has_source_separator=bool(separator_nodes)
                )
                else ""
            )
            for separator_node in separator_nodes:
                separator_node.extract()
            if separator:
                tag.append(NavigableString(separator))
            for child in list(next_tag.contents):
                tag.append(child.extract())
            next_tag.decompose()


def html_for_markdown(soup: BeautifulSoup) -> str:
    """Mutate and serialize RAG-cleaned HTML for compact Markdown conversion.

    Callers that also need prettified/debug HTML should render that output before calling this
    helper or pass a separate soup. This serializer is intentionally scoped to the RAG conversion
    corpus: it avoids prettify-created inline line breaks, preserves common tag/text separators,
    and coalesces adjacent same-formatting tags before markdownify sees them.
    """
    for node in list(soup.descendants):
        if not isinstance(node, NavigableString) or node.parent is None:
            continue
        if (
            _is_whitespace_only_text_container(node)
            and _nearest_sibling_has_nonblank_text(node.previous_sibling, previous=True)
            and _nearest_sibling_has_nonblank_text(node.next_sibling, previous=False)
        ):
            node.replace_with(NavigableString(" "))
            continue

        text = normalize_unicode_whitespace(str(node))
        normalized_text = text
        if text[:1].isspace() and _nearest_sibling_has_nonblank_text(
            node.previous_sibling, previous=True
        ):
            normalized_text = " " + normalized_text.lstrip()
        if text[-1:].isspace() and _nearest_sibling_has_nonblank_text(
            node.next_sibling, previous=False
        ):
            normalized_text = normalized_text.rstrip() + " "
        if normalized_text != str(node):
            node.replace_with(NavigableString(normalized_text))

    for tag in reversed(list(soup.find_all(name=True))):
        if not isinstance(tag, Tag) or tag.parent is None:
            continue
        text = _normalized_node_text(tag)
        if (
            text != ""
            and text.strip() == ""
            and _nearest_sibling_has_nonblank_text(tag.previous_sibling, previous=True)
            and _nearest_sibling_has_nonblank_text(tag.next_sibling, previous=False)
        ):
            tag.replace_with(NavigableString(" "))

    _merge_adjacent_format_tags(soup)

    for tag in reversed(list(soup.find_all(name=True))):
        if not isinstance(tag, Tag) or tag.parent is None:
            continue
        next_sibling = tag.next_sibling
        if next_sibling is not None and _needs_space_between(tag, next_sibling):
            tag.insert_after(NavigableString(" "))
        previous_sibling = tag.previous_sibling
        if previous_sibling is not None and _needs_space_between(previous_sibling, tag):
            tag.insert_before(NavigableString(" "))
    return str(soup)


def html_to_markdown(html_string: str) -> str:
    return markdownify(html_string, heading_style="ATX")
