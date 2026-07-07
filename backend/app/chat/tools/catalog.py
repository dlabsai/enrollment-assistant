import json
import re
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.deps import Deps
from app.chat.tools.models import CatalogDocumentResult, CatalogProgramCoursesResult
from app.models import Document as DBDocument
from app.models import DocumentType
from app.otel_genai import start_genai_tool_span
from app.rag.document_exclusions import append_va_document_exclusion_filter

_COURSE_CODE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_ -]*\d{3}[A-Z0-9_() -]*\b")
_PROGRAM_COURSE_REFERENCE_PATTERN = re.compile(
    r"(?:\[(?P<bracket_code>[A-Z][A-Z0-9_ -]*?\d{1,3}[A-Z0-9]*"
    r"(?:[- ](?:[A-Z0-9]+|\([A-Z](?:-[A-Z])?\)))*)(?:\s+-\s+[^\]]+)?\]\(#\))"
    r"|(?:(?P<bare_code>[A-Z][A-Z0-9_ -]*?\d{1,3}[A-Z0-9]*"
    r"(?:[- ](?:[A-Z0-9]+|\([A-Z](?:-[A-Z])?\)))*?)\s+-\s+(?P<bare_title>[^\n*]+))"
)


def _json_payload(value: Any) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=False)


def _set_tool_call_arguments(span: Any, **kwargs: object) -> None:
    span.set_attribute("gen_ai.tool.call.arguments", _json_payload(kwargs))


def _set_tool_call_result(span: Any, result: Any) -> None:
    span.set_attribute("gen_ai.tool.call.result", _json_payload(result))


def _catalog_document_result(row: Any) -> CatalogDocumentResult:
    return CatalogDocumentResult(type=row.type, id=row.id_, title=row.title)


async def _list_schools_db(session: AsyncSession) -> set[str]:
    conditions: list[Any] = [
        DBDocument.type == DocumentType.CATALOG_PROGRAM,
        DBDocument.school.is_not(None),
    ]
    append_va_document_exclusion_filter(conditions)
    result = await session.execute(select(DBDocument.school).where(*conditions).distinct())
    return {school for school in result.scalars().all() if school is not None}


async def _list_catalog_documents_db(
    session: AsyncSession, doc_type: DocumentType
) -> list[CatalogDocumentResult]:
    conditions: list[Any] = [DBDocument.type == doc_type]
    append_va_document_exclusion_filter(conditions)
    result = await session.execute(
        select(DBDocument.type, DBDocument.id_, DBDocument.title)
        .where(*conditions)
        .order_by(DBDocument.title)
    )
    return [_catalog_document_result(row) for row in result.all()]


async def _list_programs_by_school_db(
    session: AsyncSession, school_name: str, schools: set[str]
) -> list[CatalogDocumentResult] | None:
    if school_name not in schools:
        return None

    conditions: list[Any] = [
        DBDocument.type == DocumentType.CATALOG_PROGRAM,
        DBDocument.school == school_name,
    ]
    append_va_document_exclusion_filter(conditions)
    result = await session.execute(
        select(DBDocument.type, DBDocument.id_, DBDocument.title)
        .where(*conditions)
        .order_by(DBDocument.title)
    )
    return [_catalog_document_result(row) for row in result.all()]


def _course_code_from_title(title: str) -> str | None:
    code, separator, _ = title.partition(" - ")
    if separator and code.strip():
        return code.strip()
    match = _COURSE_CODE_PATTERN.search(title)
    return match.group(0).strip() if match else None


def _extract_program_course_references(
    markdown: str, known_course_codes: set[str] | None = None
) -> list[str]:
    indexed_references: list[tuple[int, str]] = []

    for match in _PROGRAM_COURSE_REFERENCE_PATTERN.finditer(markdown):
        code = match.group("bracket_code") or match.group("bare_code")
        if code is None:
            continue
        indexed_references.append((match.start(), code.strip()))

    if known_course_codes:
        known_code_pattern = "|".join(
            re.escape(code) for code in sorted(known_course_codes, key=len, reverse=True)
        )
        known_pattern = re.compile(
            r"(?<![A-Z0-9_-])(?P<code>" + known_code_pattern + r")(?=\s+-|\])"
        )
        for match in known_pattern.finditer(markdown):
            indexed_references.append((match.start(), match.group("code")))

        known_bracket_pattern = re.compile(
            r"\[(?P<code>" + known_code_pattern + r")(?=(?:\s+[^\]\n]+)?\]\(#\))"
        )
        for match in known_bracket_pattern.finditer(markdown):
            indexed_references.append((match.start(), match.group("code")))

    seen: set[str] = set()
    references: list[str] = []
    for _, code in sorted(indexed_references, key=lambda reference: reference[0]):
        if code in seen:
            continue
        seen.add(code)
        references.append(code)
    return references


async def _list_catalog_courses_for_program_db(
    session: AsyncSession, program_id: int
) -> CatalogProgramCoursesResult | None:
    program_conditions: list[Any] = [
        DBDocument.type == DocumentType.CATALOG_PROGRAM,
        DBDocument.id_ == program_id,
    ]
    append_va_document_exclusion_filter(program_conditions)
    program_row = (
        await session.execute(
            select(
                DBDocument.type, DBDocument.id_, DBDocument.title, DBDocument.markdown_content
            ).where(*program_conditions)
        )
    ).first()
    if program_row is None:
        return None

    course_conditions: list[Any] = [DBDocument.type == DocumentType.CATALOG_COURSE]
    append_va_document_exclusion_filter(course_conditions)
    course_rows = (
        await session.execute(
            select(DBDocument.type, DBDocument.id_, DBDocument.title).where(*course_conditions)
        )
    ).all()
    courses_by_code = {
        code: _catalog_document_result(row)
        for row in course_rows
        if (code := _course_code_from_title(row.title)) is not None
    }
    course_references = _extract_program_course_references(
        program_row.markdown_content or "", set(courses_by_code)
    )

    courses: list[CatalogDocumentResult] = []
    unmatched_course_references: list[str] = []
    for code in course_references:
        course = courses_by_code.get(code)
        if course is None:
            unmatched_course_references.append(code)
            continue
        courses.append(course)

    return CatalogProgramCoursesResult(
        program=_catalog_document_result(program_row),
        courses=courses,
        unmatched_course_references=unmatched_course_references,
    )


async def list_catalog_programs(ctx: RunContext[Deps]) -> list[CatalogDocumentResult]:
    """List catalog program document IDs and titles. Use retrieve_documents for content."""
    with start_genai_tool_span("list_catalog_programs", tool_type="datastore") as span:
        _set_tool_call_arguments(span)
        async with ctx.deps.open_tool_session() as session:
            result = await _list_catalog_documents_db(session, DocumentType.CATALOG_PROGRAM)
        _set_tool_call_result(span, result)
        return result


async def list_catalog_pages(ctx: RunContext[Deps]) -> list[CatalogDocumentResult]:
    """List catalog page document IDs and titles. Use retrieve_documents for content."""
    with start_genai_tool_span("list_catalog_pages", tool_type="datastore") as span:
        _set_tool_call_arguments(span)
        async with ctx.deps.open_tool_session() as session:
            result = await _list_catalog_documents_db(session, DocumentType.CATALOG_PAGE)
        _set_tool_call_result(span, result)
        return result


async def list_catalog_courses(ctx: RunContext[Deps]) -> list[CatalogDocumentResult]:
    """List catalog course document IDs and titles. Use retrieve_documents for content."""
    with start_genai_tool_span("list_catalog_courses", tool_type="datastore") as span:
        _set_tool_call_arguments(span)
        async with ctx.deps.open_tool_session() as session:
            result = await _list_catalog_documents_db(session, DocumentType.CATALOG_COURSE)
        _set_tool_call_result(span, result)
        return result


async def list_catalog_programs_by_school(
    ctx: RunContext[Deps], school_name: str
) -> list[CatalogDocumentResult] | None:
    """List catalog program document IDs and titles for an exact school name."""
    with start_genai_tool_span("list_catalog_programs_by_school", tool_type="datastore") as span:
        _set_tool_call_arguments(span, school_name=school_name)
        async with ctx.deps.open_tool_session() as session:
            schools = await _list_schools_db(session)
            result = await _list_programs_by_school_db(session, school_name, schools)
        _set_tool_call_result(span, result)
        return result


async def list_catalog_courses_for_program(
    ctx: RunContext[Deps], program_id: int
) -> CatalogProgramCoursesResult | None:
    """List catalog course document IDs referenced by one catalog program ID.

    Use list_catalog_programs or find_document_titles to find the program ID first.
    Use retrieve_documents for full program or course content.
    """
    with start_genai_tool_span("list_catalog_courses_for_program", tool_type="datastore") as span:
        _set_tool_call_arguments(span, program_id=program_id)
        async with ctx.deps.open_tool_session() as session:
            result = await _list_catalog_courses_for_program_db(session, program_id)
        _set_tool_call_result(span, result)
        return result
