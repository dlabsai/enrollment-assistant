from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db_observability import InteractiveAsyncSession, MainAsyncSession, instrument_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _create_database_engine(
    *, pool_size: int, max_overflow: int, pool_timeout: float
) -> AsyncEngine:
    return create_async_engine(
        str(settings.SQLALCHEMY_DATABASE_URI).replace("postgresql://", "postgresql+psycopg://"),
        echo=False,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        connect_args={
            "options": (
                f"-c hnsw.ef_search={settings.HNSW_EF_SEARCH} "
                f"-c hnsw.iterative_scan={settings.HNSW_ITERATIVE_SCAN}"
            )
        },
    )


# Each web worker owns two bounded product pools. Transactions end before model waits,
# while latency-sensitive list GETs have independently queued connection capacity.
engine = _create_database_engine(
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_timeout=settings.POSTGRES_POOL_TIMEOUT_SECONDS,
)
interactive_engine = _create_database_engine(
    pool_size=settings.INTERACTIVE_POSTGRES_POOL_SIZE,
    max_overflow=settings.INTERACTIVE_POSTGRES_MAX_OVERFLOW,
    pool_timeout=settings.INTERACTIVE_POSTGRES_POOL_TIMEOUT_SECONDS,
)
instrument_async_engine(engine, pool_name="main")
instrument_async_engine(interactive_engine, pool_name="interactive")
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=MainAsyncSession)
interactive_async_session_factory = async_sessionmaker(
    interactive_engine, expire_on_commit=False, class_=InteractiveAsyncSession
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_interactive_session() -> AsyncGenerator[AsyncSession]:
    async with interactive_async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_database_pools() -> None:
    try:
        await interactive_engine.dispose()
    finally:
        await engine.dispose()
