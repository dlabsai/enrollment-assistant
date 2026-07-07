"""Guarded test/eval database setup shared by pytest and app eval runners."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.core.rbac import seed_system_groups
from app.evals.rag_data import (
    check_rag_data_exists,
    create_session_factory,
    get_rag_data_stats,
    populate_rag_data,
)
from app.models import Base


class EvalDatabaseConfigError(RuntimeError):
    """Raised when guarded eval/test database configuration is unsafe."""


def load_eval_database_url() -> str:
    """Validate PYTEST_POSTGRES_* settings and return the guarded eval DB URL."""
    missing = [
        name
        for name, value in {
            "PYTEST_POSTGRES_SERVER": settings.PYTEST_POSTGRES_SERVER,
            "PYTEST_POSTGRES_PORT": settings.PYTEST_POSTGRES_PORT,
            "PYTEST_POSTGRES_USER": settings.PYTEST_POSTGRES_USER,
            "PYTEST_POSTGRES_PASSWORD": settings.PYTEST_POSTGRES_PASSWORD,
            "PYTEST_POSTGRES_DB": settings.PYTEST_POSTGRES_DB,
        }.items()
        if value in {"", 0}
    ]
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise EvalDatabaseConfigError(f"Tests require external DB env vars: {missing_text}")

    if not settings.PYTEST_POSTGRES_DB.endswith("_test"):
        raise EvalDatabaseConfigError(
            "Unsafe PYTEST_POSTGRES_DB value. Test database name must end with '_test'."
        )

    if settings.POSTGRES_DB != "" and settings.POSTGRES_DB == settings.PYTEST_POSTGRES_DB:
        raise EvalDatabaseConfigError(
            "Unsafe DB configuration: PYTEST_POSTGRES_DB must differ from POSTGRES_DB."
        )

    return str(settings.PYTEST_SQLALCHEMY_DATABASE_URI)


def run_test_db_migrations(database_url: str) -> None:
    """Run Alembic migrations against the guarded test/eval database."""
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")


def create_test_db_engine(database_url: str) -> AsyncEngine:
    """Create an async engine for the guarded test/eval database."""
    return create_async_engine(database_url, echo=False)


async def initialize_test_db_schema(engine: AsyncEngine) -> None:
    """Create extensions/tables and seed static RBAC data idempotently."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_system_groups(session)
        await session.commit()


async def ensure_test_db_rag_data(engine: AsyncEngine, *, rebuild_rag: bool) -> dict[str, int]:
    """Ensure RAG data exists in the guarded test/eval database."""
    rag_exists = await check_rag_data_exists(engine)
    if rebuild_rag or not rag_exists:
        await populate_rag_data(engine)

    return await get_rag_data_stats(engine)


async def prepare_test_db_engine(*, rebuild_rag: bool, database_url: str) -> AsyncEngine:
    """Create and initialize an eval/test DB engine, including optional RAG rebuild."""
    engine = create_test_db_engine(database_url)
    await initialize_test_db_schema(engine)
    await ensure_test_db_rag_data(engine, rebuild_rag=rebuild_rag)
    return engine


def load_and_migrate_eval_database() -> str:
    """Load guarded eval DB URL and run migrations without mutating runtime DB env."""
    database_url = load_eval_database_url()
    run_test_db_migrations(database_url)
    return database_url
