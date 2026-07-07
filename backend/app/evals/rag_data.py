"""Eval RAG data helpers used by app runtime and pytest wrappers."""

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Document, DocumentContentChunk

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory with consistent settings."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def _get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Create a session from an engine."""
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        yield session


async def check_rag_data_exists(engine: AsyncEngine) -> bool:
    """Check whether RAG documents already exist in the eval database."""
    async with _get_session(engine) as session:
        result = await session.execute(select(func.count(Document.id)))
        count = result.scalar()
        return count is not None and count > 0


async def get_rag_data_stats(engine: AsyncEngine) -> dict[str, int]:
    """Get statistics about eval RAG data."""
    async with _get_session(engine) as session:
        doc_result = await session.execute(select(func.count(Document.id)))
        doc_count = doc_result.scalar() or 0

        chunk_result = await session.execute(select(func.count(DocumentContentChunk.id)))
        chunk_count = chunk_result.scalar() or 0

        type_result = await session.execute(
            select(Document.type, func.count(Document.id)).group_by(Document.type)
        )
        type_counts = {row[0]: row[1] for row in type_result.fetchall()}

        return {
            "total_documents": doc_count,
            "total_chunks": chunk_count,
            **{f"doc_type_{key}": value for key, value in type_counts.items()},
        }


async def populate_rag_data(engine: AsyncEngine) -> None:
    """Populate eval RAG data with a forced search DB rebuild on the supplied engine."""
    # Import lazily so pytest can configure guarded POSTGRES_* env before app.core.db is loaded.
    from app.chat.tools.utils import get_azure_openai_client  # noqa: PLC0415
    from app.rag.build import build_search_db  # noqa: PLC0415

    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await build_search_db(get_azure_openai_client(), session, force_rebuild=True, dry_run=False)


def run_rag_population_sync(engine: AsyncEngine) -> None:
    """Wrap populate_rag_data for synchronous execution."""
    asyncio.run(populate_rag_data(engine))
