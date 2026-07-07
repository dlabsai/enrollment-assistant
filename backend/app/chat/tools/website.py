import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools.deps import Deps
from app.models import Document as DBDocument
from app.models import DocumentType
from app.otel_genai import start_genai_tool_span
from app.rag.document_exclusions import append_va_document_exclusion_filter


async def _list_pages_db(session: AsyncSession) -> list[tuple[int, str]]:
    """Get all non-excluded website page IDs and titles from database."""
    conditions: list[Any] = [DBDocument.type == DocumentType.WEBSITE_PAGE]
    append_va_document_exclusion_filter(conditions)
    stmt = select(DBDocument.id_, DBDocument.title).where(*conditions)
    result = await session.execute(stmt)
    rows = result.all()
    return [(row.id_, row.title) for row in rows]


async def _list_programs_db(session: AsyncSession) -> list[tuple[int, str]]:
    """Get all non-excluded website program IDs and titles from database."""
    conditions: list[Any] = [DBDocument.type == DocumentType.WEBSITE_PROGRAM]
    append_va_document_exclusion_filter(conditions)
    stmt = select(DBDocument.id_, DBDocument.title).where(*conditions)
    result = await session.execute(stmt)
    rows = result.all()
    return [(row.id_, row.title) for row in rows]


# PydanticAI tool wrappers with ctx argument and docstrings


def _json_payload(value: Any) -> str:
    return json.dumps(jsonable_encoder(value), ensure_ascii=False)


async def list_website_pages(ctx: RunContext[Deps]) -> list[tuple[int, str]]:
    """Get website page IDs and titles."""
    with start_genai_tool_span("list_website_pages", tool_type="datastore") as span:
        span.set_attribute("gen_ai.tool.call.arguments", "{}")
        async with ctx.deps.open_tool_session() as session:
            result = await _list_pages_db(session)
        span.set_attribute("gen_ai.tool.call.result", _json_payload(result))
        return result


async def list_website_programs(ctx: RunContext[Deps]) -> list[tuple[int, str]]:
    """Get website program IDs and titles."""
    with start_genai_tool_span("list_website_programs", tool_type="datastore") as span:
        span.set_attribute("gen_ai.tool.call.arguments", "{}")
        async with ctx.deps.open_tool_session() as session:
            result = await _list_programs_db(session)
        span.set_attribute("gen_ai.tool.call.result", _json_payload(result))
        return result
