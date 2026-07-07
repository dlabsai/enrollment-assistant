# ruff: noqa: E402

import os
import uuid
from typing import TYPE_CHECKING, cast

_PYTEST_POSTGRES_ENV_MAP = {
    "PYTEST_POSTGRES_SERVER": "POSTGRES_SERVER",
    "PYTEST_POSTGRES_PORT": "POSTGRES_PORT",
    "PYTEST_POSTGRES_USER": "POSTGRES_USER",
    "PYTEST_POSTGRES_PASSWORD": "POSTGRES_PASSWORD",
    "PYTEST_POSTGRES_DB": "POSTGRES_DB",
}

_missing = [key for key in _PYTEST_POSTGRES_ENV_MAP if os.environ.get(key, "").strip() == ""]
if _missing:
    raise RuntimeError(f"Tests require external DB env vars: {', '.join(sorted(_missing))}")

_pytest_db = os.environ["PYTEST_POSTGRES_DB"].strip()
_runtime_db = os.environ.get("POSTGRES_DB", "").strip()
if not _pytest_db.endswith("_test"):
    raise RuntimeError("Unsafe PYTEST_POSTGRES_DB value. Test database name must end with '_test'.")
if _runtime_db != "" and _runtime_db == _pytest_db:
    raise RuntimeError("Unsafe DB configuration: PYTEST_POSTGRES_DB must differ from POSTGRES_DB.")

for _source, _target in _PYTEST_POSTGRES_ENV_MAP.items():
    os.environ[_target] = os.environ[_source]

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.rag_data import create_session_factory
from app.evals.test_db import (
    create_test_db_engine,
    ensure_test_db_rag_data,
    initialize_test_db_schema,
    run_test_db_migrations,
)
from app.models import User

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Fixed UUID for centralized test user
TEST_USER_ID = uuid.UUID("12345678-1234-5678-9abc-123456789012")

# Module-scoped engine/session factory for all tests
_test_engine = None
_test_session_factory = None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--rebuild-rag",
        action="store_true",
        default=False,
        help="Force rebuild of RAG data (expensive - calls embedding API)",
    )
    parser.addoption(
        "--repeat",
        "-R",
        action="store",
        type=int,
        default=1,
        help="Number of times to repeat each LLM judge test case (default: 1)",
    )
    parser.addoption(
        "--max-concurrency",
        "-C",
        action="store",
        type=int,
        default=5,
        help="Maximum concurrent LLM calls per test case (default: 5)",
    )
    parser.addoption(
        "--test-cases",
        "-T",
        action="store",
        type=str,
        default=None,
        help="Comma-separated list of test case IDs to run "
        "(e.g., 'greeting_response,accreditation_inquiry')",
    )
    parser.addoption(
        "--pass-threshold",
        "-P",
        action="store",
        type=float,
        default=0.9,
        help="Minimum pass rate threshold for each test case (default: 0.9 = 90%%)",
    )
    parser.addoption(
        "--chatbot-model",
        action="store",
        type=str,
        default=None,
        help="Override the chatbot model for evals.",
    )
    parser.addoption(
        "--guardrail-model",
        action="store",
        type=str,
        default=None,
        help="Override the guardrails model for evals.",
    )
    parser.addoption(
        "--evaluation-model",
        action="store",
        type=str,
        default=None,
        help="Override the evaluation model for evals.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Migrate the configured guarded test database."""
    from app.core.config import settings

    run_test_db_migrations(str(settings.SQLALCHEMY_DATABASE_URI))


def pytest_unconfigure(config: pytest.Config) -> None:
    """Pytest shutdown hook."""
    del config


@pytest_asyncio.fixture(scope="session")
async def db_engine(request: pytest.FixtureRequest):
    """Create the database engine and tables once per test session.

    Uses the external test database selected in `pytest_configure`.
    If --rebuild-rag is passed, will rebuild RAG data (expensive).
    """
    global _test_engine, _test_session_factory  # noqa: PLW0603

    from app.core.config import settings

    _test_engine = create_test_db_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    _test_session_factory = create_session_factory(_test_engine)

    await initialize_test_db_schema(_test_engine)

    # Check if RAG data needs to be populated
    rebuild_rag = cast(bool, request.config.getoption("--rebuild-rag", default=False))
    stats = await ensure_test_db_rag_data(_test_engine, rebuild_rag=rebuild_rag)
    status = "RAG data rebuilt/populated" if rebuild_rag else "RAG data ready"
    print(f"\n✅ {status}: {stats['total_documents']} documents, {stats['total_chunks']} chunks")

    yield _test_engine

    await _test_engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: object) -> AsyncGenerator[AsyncSession]:
    """Create a test database session with transaction rollback.

    Each test gets its own transaction that is rolled back after the test completes,
    ensuring test isolation. Any data created during the test will not persist.
    """
    if _test_session_factory is None:
        raise RuntimeError("Test session factory not initialized")
    if _test_engine is None:
        raise RuntimeError("Test engine not initialized")

    # Get a connection and start a transaction
    async with _test_engine.connect() as connection:
        # Start a transaction that will be rolled back
        transaction = await connection.begin()

        # Create a session bound to this connection
        async with _test_session_factory(bind=connection) as session:
            # Disable the session's ability to commit (nested transactions go to savepoints)
            yield session

        # Rollback the transaction after the test
        await transaction.rollback()


@pytest_asyncio.fixture
async def transactional_session(db_engine: object) -> AsyncGenerator[AsyncSession]:
    """Create a transactional test session that rolls back all test changes."""
    from app.api.deps import get_db_session
    from app.main import app

    if _test_session_factory is None:
        raise RuntimeError("Test session factory not initialized")
    if _test_engine is None:
        raise RuntimeError("Test engine not initialized")

    async with _test_engine.connect() as connection:
        transaction = await connection.begin()
        async with _test_session_factory(bind=connection) as session:

            async def override_get_db_session() -> AsyncGenerator[AsyncSession]:
                request_transaction = await session.begin_nested()
                try:
                    yield session
                    if request_transaction.is_active:
                        await request_transaction.commit()
                except Exception:
                    if request_transaction.is_active:
                        await request_transaction.rollback()
                    raise

            app.dependency_overrides[get_db_session] = override_get_db_session
            try:
                yield session
            finally:
                app.dependency_overrides.pop(get_db_session, None)

        await transaction.rollback()


@pytest_asyncio.fixture
async def test_user(session: AsyncSession) -> User:
    """Create a centralized test user for testing."""
    # Check if user already exists by ID
    existing_user = await session.get(User, TEST_USER_ID)
    if existing_user:
        return existing_user

    # Check if user exists by email (in case of ID mismatch)
    stmt = select(User).filter_by(email="test@example.com")
    result = await session.execute(stmt)
    existing_user_by_email = result.scalar_one_or_none()
    if existing_user_by_email:
        return existing_user_by_email

    # Use a pre-generated bcrypt hash for "testpass123" to avoid bcrypt issues in tests
    # This is a valid bcrypt hash generated for "testpass123"
    precomputed_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.R.HqhAW5a3QBGG"
    from app.core.rbac import SystemGroupSlug, get_group_for_slug

    group = await get_group_for_slug(session, SystemGroupSlug.USER)

    user = User(
        id=TEST_USER_ID,
        email="test@example.com",
        name="Test User",
        password_hash=precomputed_hash,
        is_active=True,
        group_id=group.id,
    )
    session.add(user)
    try:
        await session.commit()
        await session.refresh(user)

    except Exception:
        await session.rollback()
        # If commit failed, try to get the user again (race condition)
        existing_user = await session.get(User, TEST_USER_ID)
        if existing_user:
            return existing_user
        stmt = select(User).filter_by(email="test@example.com")
        result = await session.execute(stmt)
        existing_user_by_email = result.scalar_one_or_none()
        if existing_user_by_email:
            return existing_user_by_email
        raise
    else:
        return user


@pytest.fixture
def model() -> str:
    from app.core.config import settings

    return settings.CHATBOT_MODEL
