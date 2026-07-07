from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from jinja2 import Environment
from openai import AsyncOpenAI

from app.chat.config import TEMPLATES_DIR
from app.chat.template_utils import get_jinja_environment
from app.chat.tools.utils import get_azure_openai_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class Deps:
    """Dependencies for PydanticAI agents with tools.

    This is the single source of truth for the is_internal configuration.
    Tools and jinja_env are derived properties based on is_internal.
    """

    openai: AsyncOpenAI
    session_factory: async_sessionmaker[AsyncSession]
    is_internal: bool = False
    investigation_conversation_id: UUID | None = None
    prompt_set_version_id: UUID | None = None
    _tools: list[Any] = field(default_factory=lambda: cast(list[Any], []), repr=False)
    _jinja_env: Environment | None = field(default=None, repr=False)

    @property
    def tools(self) -> list[Any]:
        """Get the appropriate tools list based on conversation/tool mode."""
        if not self._tools:
            from app.chat.tools import (  # noqa: PLC0415
                INTERNAL_TOOLS,
                INVESTIGATION_TOOLS,
                PUBLIC_TOOLS,
            )

            if self.investigation_conversation_id is not None:
                self._tools = [*INVESTIGATION_TOOLS]
            else:
                self._tools = [*INTERNAL_TOOLS] if self.is_internal else [*PUBLIC_TOOLS]
        return self._tools

    @property
    def jinja_env(self) -> Environment:
        """Get the cached Jinja environment for the template directory and mode."""
        if self._jinja_env is None:
            self._jinja_env = get_jinja_environment(TEMPLATES_DIR, is_internal=self.is_internal)
        return self._jinja_env

    @asynccontextmanager
    async def open_tool_session(self) -> AsyncGenerator[AsyncSession]:
        """Open a fresh database session for a single tool invocation."""
        async with self.session_factory() as session:
            yield session


def get_deps(
    *, session_factory: async_sessionmaker[AsyncSession], is_internal: bool = False
) -> Deps:
    """Create a Deps instance with all derived properties.

    This is the main entry point for creating dependencies.
    Uses disk templates by default.
    """
    return Deps(
        openai=get_azure_openai_client(), is_internal=is_internal, session_factory=session_factory
    )


def get_deps_with_jinja_env(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    is_internal: bool = False,
    jinja_env: Environment,
    prompt_set_version_id: UUID | None = None,
    investigation_conversation_id: UUID | None = None,
) -> Deps:
    """Create a Deps instance with a pre-resolved Jinja environment.

    Args:
        session_factory: Database session factory for tools. Each tool call opens its own session
        is_internal: Whether to use internal mode (affects tools and internal template variants)
        jinja_env: The already resolved Jinja environment to use at runtime
        prompt_set_version_id: The ID of the prompt-set version being used (for tracking)
        investigation_conversation_id: Current investigation conversation for source-inspection
            tools

    """
    return Deps(
        openai=get_azure_openai_client(),
        is_internal=is_internal,
        investigation_conversation_id=investigation_conversation_id,
        prompt_set_version_id=prompt_set_version_id,
        session_factory=session_factory,
        _jinja_env=jinja_env,
    )
