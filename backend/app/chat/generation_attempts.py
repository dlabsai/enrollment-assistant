from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import update

from app.models import ChatGenerationAttempt
from app.utils import current_time_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

GENERATION_ATTEMPT_PENDING = "pending"
GENERATION_ATTEMPT_COMPLETED = "completed"
GENERATION_ATTEMPT_FAILED = "failed"

# Observed completions take minutes at most and each provider call times out after five, so a
# pending attempt this old has lost its worker (restart or crash), not a slow generation.
STALE_GENERATION_ATTEMPT_AFTER = timedelta(minutes=15)


async def fail_stale_generation_attempts(
    session: AsyncSession, *, stale_after: timedelta = STALE_GENERATION_ATTEMPT_AFTER
) -> int:
    """Move pending attempts whose worker is gone to failed and return how many moved.

    One atomic conditional update, so concurrent sweeps cannot double-apply it.
    """
    result = await session.execute(
        update(ChatGenerationAttempt)
        .where(
            ChatGenerationAttempt.status == GENERATION_ATTEMPT_PENDING,
            ChatGenerationAttempt.created_at < current_time_utc() - stale_after,
        )
        .values(status=GENERATION_ATTEMPT_FAILED)
        .returning(ChatGenerationAttempt.id)
    )
    failed_count = len(result.all())
    await session.commit()
    return failed_count
