"""Restore full-text search omitted by the OSS squashed initial schema.

Revision ID: f217e562bd85
Revises: 581d5fbd700c
Create Date: 2026-09-11 17:20:18.714025

"""

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f217e562bd85"
down_revision: str | None = "581d5fbd700c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEARCH_VECTOR_EXPRESSION = """
setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
setweight(to_tsvector('simple', coalesce(url, '')), 'B') ||
setweight(to_tsvector('simple', coalesce(markdown_content, '')), 'C')
"""


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE document
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPRESSION}) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_search_vector
        ON document
        USING gin (search_vector)
        """
    )


def downgrade() -> None:
    # This repairs a baseline schema invariant and may adopt a column created by
    # the pre-squash history, so downgrading must not remove shared data/indexes.
    pass
