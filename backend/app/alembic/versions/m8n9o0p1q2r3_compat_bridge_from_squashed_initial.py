"""Compatibility bridge from the squashed initial schema.

Revision ID: m8n9o0p1q2r3
Revises: 18cd31149b5d
Create Date: 2026-07-16 22:00:00.000000

This intentionally empty revision preserves compatibility with databases that
were stamped at the pre-squash migration revision m8n9o0p1q2r3. New databases
apply the squashed initial schema, pass through this no-op revision, then apply
post-squash migrations normally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "m8n9o0p1q2r3"
down_revision: str | None = "18cd31149b5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
