from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.url_guardrails_config import get_prompt_allowed_urls
from app.models import Document, DocumentType, GuardrailUrlRegistry
from app.rag.training_materials.urls import training_material_demo_url_from_url
from app.utils import current_time_utc

if TYPE_CHECKING:
    from collections.abc import Iterable

_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>*"
_RELATIVE_URL_BASE = "https://demo-university.example.edu"
_WWW_HOST_ALIASES = {
    "www.demo-university.example.edu": "demo-university.example.edu",
    "www.catalog.demo-university.example.edu": "catalog.demo-university.example.edu",
}

_HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_MAILTO_PATTERN = re.compile(r"mailto:[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_RELATIVE_URL_PATTERN = re.compile(r"(?<![\w@<])/(?!/)[A-Za-z0-9][^\s<>()\[\]{}\"']*")
_BARE_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",
    re.IGNORECASE,
)
_BARE_DOMAIN_PATTERN = re.compile(
    r"(?<![@\w])"
    r"(?:www\.)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}"
    r"(?::\d{2,5})?"
    r"(?:[/?#][^\s<>()\[\]{}\"']*)?",
    re.IGNORECASE,
)
_URL_EXTRACTOR_PATTERNS = (
    _HTTP_URL_PATTERN,
    _MAILTO_PATTERN,
    _RELATIVE_URL_PATTERN,
    _BARE_EMAIL_PATTERN,
    _BARE_DOMAIN_PATTERN,
)
_URL_REGISTRY_VERSION = "v7"


def _is_allowed_response_url(normalized_url: str, *, allowed_urls: frozenset[str]) -> bool:
    if normalized_url in allowed_urls:
        return True

    # Allow a response to use HTTPS for a known HTTP source target, but do not
    # allow the reverse downgrade from a known HTTPS source target to HTTP.
    parts = urlsplit(normalized_url)
    if parts.scheme != "https":
        return False
    http_source_url = urlunsplit(("http", parts.netloc, parts.path, parts.query, ""))
    return http_source_url in allowed_urls


def extract_urls(text: str) -> list[str]:
    if text == "":
        return []

    matches: list[tuple[int, int, str]] = []
    for pattern in _URL_EXTRACTOR_PATTERNS:
        for match in pattern.finditer(text):
            raw_value = match.group(0)
            cleaned_value = raw_value.rstrip(_TRAILING_URL_PUNCTUATION)
            if cleaned_value == "":
                continue
            cleaned_end = match.start() + len(cleaned_value)
            matches.append((match.start(), cleaned_end, cleaned_value))

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))

    extracted: list[str] = []
    accepted_ranges: list[tuple[int, int]] = []
    for start, end, value in matches:
        if any(
            existing_start <= start and end <= existing_end
            for existing_start, existing_end in accepted_ranges
        ):
            continue
        extracted.append(value)
        accepted_ranges.append((start, end))

    return extracted


def _normalize_host(netloc: str) -> str:
    lowered = netloc.lower()
    return _WWW_HOST_ALIASES.get(lowered, lowered)


def _normalize_mailto(candidate: str) -> str | None:
    parts = urlsplit(candidate)
    email = parts.path.strip().lower()
    if _BARE_EMAIL_PATTERN.fullmatch(email) is None:
        return None
    return urlunsplit(("mailto", "", email, parts.query, ""))


def normalize_url(url: str) -> str | None:
    candidate = unescape(url).strip().rstrip(_TRAILING_URL_PUNCTUATION)
    if candidate == "":
        return None

    if candidate.lower().startswith("mailto:"):
        return _normalize_mailto(candidate)

    if _BARE_EMAIL_PATTERN.fullmatch(candidate) is not None:
        return _normalize_mailto(f"mailto:{candidate}")

    if _RELATIVE_URL_PATTERN.fullmatch(candidate) is not None:
        return normalize_url(f"{_RELATIVE_URL_BASE}{candidate}")

    if _BARE_DOMAIN_PATTERN.fullmatch(candidate) is not None:
        return normalize_url(f"https://{candidate}")

    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"} or parts.netloc == "":
        return None

    scheme = parts.scheme.lower()
    netloc = _normalize_host(parts.netloc)
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    return urlunsplit((scheme, netloc, path, parts.query, ""))


def collect_normalized_urls(text: str) -> set[str]:
    normalized_urls: set[str] = set()
    for url in extract_urls(text):
        normalized_url = normalize_url(url)
        if normalized_url is not None:
            normalized_urls.add(normalized_url)
    return normalized_urls


def is_blog_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return "/blog" in path


def get_guardrail_url_registry_key(*, is_internal: bool) -> str:
    va_scope = "internal" if is_internal else "public"
    return f"{va_scope}_{_URL_REGISTRY_VERSION}"


async def build_allowed_url_registry(
    session: AsyncSession, *, extra_urls: Iterable[str] = (), is_internal: bool = True
) -> frozenset[str]:
    stmt = select(Document.url, Document.markdown_content)
    if not is_internal:
        stmt = stmt.where(Document.type != DocumentType.TRAINING_MATERIAL)
    rows = (await session.execute(stmt)).all()

    allowed_urls: set[str] = set()
    for document_url, markdown_content in rows:
        effective_document_url = document_url
        if is_internal and document_url.startswith("training-materials://"):
            effective_document_url = training_material_demo_url_from_url(document_url)
        normalized_document_url = normalize_url(effective_document_url)
        if normalized_document_url is not None and not is_blog_url(normalized_document_url):
            allowed_urls.add(normalized_document_url)
        for url in collect_normalized_urls(markdown_content):
            if not is_blog_url(url):
                allowed_urls.add(url)

    for extra_url in extra_urls:
        normalized_extra_url = normalize_url(extra_url)
        if normalized_extra_url is None:
            continue
        if not is_blog_url(normalized_extra_url):
            allowed_urls.add(normalized_extra_url)

    return frozenset(allowed_urls)


async def _upsert_guardrail_url_registry(
    session: AsyncSession, *, key: str, urls: frozenset[str]
) -> None:
    sorted_urls = sorted(urls)
    now = current_time_utc()
    await session.execute(
        insert(GuardrailUrlRegistry)
        .values(id=uuid4(), created_at=now, updated_at=now, key=key, urls=sorted_urls)
        .on_conflict_do_update(
            index_elements=[GuardrailUrlRegistry.key], set_={"urls": sorted_urls, "updated_at": now}
        )
    )


async def load_guardrail_url_registry(session: AsyncSession, *, key: str) -> frozenset[str] | None:
    urls = (
        await session.execute(
            select(GuardrailUrlRegistry.urls).where(GuardrailUrlRegistry.key == key)
        )
    ).scalar_one_or_none()
    if urls is None:
        return None
    return frozenset(urls)


async def get_allowed_url_registry_for_va(
    session: AsyncSession, *, is_internal: bool
) -> frozenset[str]:
    key = get_guardrail_url_registry_key(is_internal=is_internal)
    persisted_registry = await load_guardrail_url_registry(session, key=key)
    if persisted_registry is not None:
        return persisted_registry

    computed_registry = await build_allowed_url_registry(
        session,
        extra_urls=get_prompt_allowed_urls(is_internal=is_internal),
        is_internal=is_internal,
    )
    await _upsert_guardrail_url_registry(session, key=key, urls=computed_registry)
    return computed_registry


async def refresh_guardrail_url_registries(session: AsyncSession) -> None:
    for is_internal in (False, True):
        urls = await build_allowed_url_registry(
            session,
            extra_urls=get_prompt_allowed_urls(is_internal=is_internal),
            is_internal=is_internal,
        )
        await _upsert_guardrail_url_registry(
            session, key=get_guardrail_url_registry_key(is_internal=is_internal), urls=urls
        )


def find_unknown_urls(text: str, *, allowed_urls: frozenset[str]) -> list[str]:
    unknown_urls: list[str] = []
    seen_urls: set[str] = set()

    for url in extract_urls(text):
        normalized_url = normalize_url(url)
        if (
            normalized_url is None
            or _is_allowed_response_url(normalized_url, allowed_urls=allowed_urls)
            or normalized_url in seen_urls
        ):
            continue
        unknown_urls.append(normalized_url)
        seen_urls.add(normalized_url)

    return unknown_urls


def find_blog_urls(text: str) -> list[str]:
    blog_urls: list[str] = []
    seen_urls: set[str] = set()

    for url in extract_urls(text):
        normalized_url = normalize_url(url)
        if normalized_url is None or normalized_url in seen_urls or not is_blog_url(normalized_url):
            continue
        blog_urls.append(normalized_url)
        seen_urls.add(normalized_url)

    return blog_urls


def build_unknown_url_feedback(unknown_urls: list[str]) -> str:
    url_list = "\n".join(f"- {url}" for url in unknown_urls)
    return (
        "The response includes link target(s) that are not present in the known registry built "
        "from indexed document URLs and indexed document content:\n"
        f"{url_list}\n"
        "Remove those link target(s) or replace them only with target(s) that already exist in "
        "the known registry. Do not invent or guess links, email addresses, or URLs."
    )


def build_blog_url_feedback(blog_urls: list[str]) -> str:
    url_list = "\n".join(f"- {url}" for url in blog_urls)
    return (
        "The response includes disallowed blog URL(s). Any URL whose path contains `/blog` "
        "must be removed from the response:\n"
        f"{url_list}"
    )
