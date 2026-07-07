from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import SystemGroupSlug, get_group_for_slug
from app.core.security import get_password_hash
from app.evals.rag_copy import _copy_model_rows  # pyright: ignore[reportPrivateUsage]
from app.models import RagDocumentExclusion, User


class _FakeDestinationSession:
    def __init__(self) -> None:
        self.rows: list[RagDocumentExclusion] = []

    def add_all(self, rows: list[RagDocumentExclusion]) -> None:
        self.rows.extend(rows)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_copy_model_rows_copies_exclusion_policy_without_runtime_user_fk(
    transactional_session: AsyncSession,
) -> None:
    group = await get_group_for_slug(transactional_session, SystemGroupSlug.ADMIN)
    user = User(
        email=f"rag-copy-{uuid4()}@example.com",
        name="RAG Copy User",
        password_hash=get_password_hash("StrongPassword123"),
        is_active=True,
        group_id=group.id,
    )
    source_key = f"copy-test:{uuid4()}"
    transactional_session.add(user)
    transactional_session.add(
        RagDocumentExclusion(
            source_key=source_key, reason="Copied exclusion", created_by_user_id=user.id
        )
    )
    await transactional_session.flush()

    destination_session = _FakeDestinationSession()
    count = await _copy_model_rows(
        transactional_session,
        destination_session,  # pyright: ignore[reportArgumentType]
        RagDocumentExclusion,
        column_overrides={"created_by_user_id": None},
        row_label_singular="document exclusion",
        row_label_plural="document exclusions",
    )

    copied_row = next(row for row in destination_session.rows if row.source_key == source_key)
    assert count >= 1
    assert copied_row.reason == "Copied exclusion"
    assert copied_row.created_by_user_id is None
