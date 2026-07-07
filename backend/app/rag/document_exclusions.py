from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.sql.selectable import Exists

from app.models import Document, RagDocumentExclusion

RagExclusionFilter = Literal["all", "included", "excluded"]


def is_document_excluded_expr() -> Exists:
    return (
        select(RagDocumentExclusion.id)
        .where(RagDocumentExclusion.source_key == Document.source_key)
        .correlate(Document)
        .exists()
    )


def apply_exclusion_filter(conditions: list[Any], exclusion: RagExclusionFilter) -> None:
    excluded_expr = is_document_excluded_expr()
    if exclusion == "included":
        conditions.append(~excluded_expr)
    elif exclusion == "excluded":
        conditions.append(excluded_expr)


def append_va_document_exclusion_filter(conditions: list[Any]) -> None:
    conditions.append(~is_document_excluded_expr())
