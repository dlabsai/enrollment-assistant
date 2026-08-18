import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.chat.template_utils import (
    clear_deployed_templates_cache,
    get_deployed_templates,
    get_templates_for_version,
)
from app.core.db import engine
from app.models import PromptSetScope

if TYPE_CHECKING:
    from collections.abc import Callable


def _record_prompt_queries(
    counters: dict[str, int],
) -> Callable[[Any, Any, str, Any, Any, Any], None]:
    def record_query(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        normalized = statement.casefold()
        if "from prompt_set_version" in normalized:
            counters["versions"] += 1
        if "from prompt_set_template" in normalized:
            counters["templates"] += 1

    return record_query


@pytest.mark.asyncio
async def test_deployed_template_cold_load_is_single_flight(db_engine: object) -> None:
    del db_engine
    clear_deployed_templates_cache()
    counters = {"versions": 0, "templates": 0}
    record_query = _record_prompt_queries(counters)
    event.listen(engine.sync_engine, "before_cursor_execute", record_query)

    try:
        results = await asyncio.gather(
            *(
                get_deployed_templates(is_internal=True, scope=PromptSetScope.ASSISTANT)
                for _ in range(250)
            )
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_query)
        clear_deployed_templates_cache()

    assert counters["versions"] == 1
    assert counters["templates"] <= 1
    assert all(templates == results[0] for templates in results)


@pytest.mark.asyncio
async def test_template_cache_clear_discards_in_flight_load(db_engine: object) -> None:
    del db_engine
    clear_deployed_templates_cache()
    template_queries = 0
    version_id = uuid4()

    def clear_during_first_query(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        nonlocal template_queries
        if "from prompt_set_template" not in statement.casefold():
            return
        template_queries += 1
        if template_queries == 1:
            clear_deployed_templates_cache()

    event.listen(engine.sync_engine, "before_cursor_execute", clear_during_first_query)
    try:
        first = await get_templates_for_version(version_id)
        second = await get_templates_for_version(version_id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", clear_during_first_query)
        clear_deployed_templates_cache()

    assert template_queries == 2
    assert first == second == {}


@pytest.mark.asyncio
async def test_version_template_cold_load_is_single_flight(db_engine: object) -> None:
    del db_engine
    clear_deployed_templates_cache()
    counters = {"versions": 0, "templates": 0}
    version_id = uuid4()
    record_query = _record_prompt_queries(counters)
    event.listen(engine.sync_engine, "before_cursor_execute", record_query)

    try:
        results = await asyncio.gather(*(get_templates_for_version(version_id) for _ in range(250)))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_query)
        clear_deployed_templates_cache()

    assert counters == {"versions": 0, "templates": 1}
    assert results == [{}] * 250
