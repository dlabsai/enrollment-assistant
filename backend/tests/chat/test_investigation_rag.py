from __future__ import annotations

from typing import Any, cast

import pytest

from app.chat.tools.investigation_rag import (
    audit_rag_content_search,
    audit_rag_title_search,
    list_rag_documents,
)


@pytest.mark.asyncio
async def test_investigation_rag_content_search_rejects_oversized_limit() -> None:
    with pytest.raises(ValueError, match="limit must be less than or equal to 200"):
        await audit_rag_content_search(cast(Any, object()), "tuition", limit=201)


@pytest.mark.asyncio
async def test_investigation_rag_title_search_rejects_oversized_limit() -> None:
    with pytest.raises(ValueError, match="limit must be less than or equal to 500"):
        await audit_rag_title_search(cast(Any, object()), "tuition", limit=501)


@pytest.mark.asyncio
async def test_investigation_rag_document_listing_rejects_oversized_page_size() -> None:
    with pytest.raises(ValueError, match="page_size must be less than or equal to 100"):
        await list_rag_documents(cast(Any, object()), page_size=101)
