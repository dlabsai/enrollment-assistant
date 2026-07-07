from typing import TYPE_CHECKING

from jinja2 import BaseLoader, Environment, FileSystemLoader
from sqlalchemy import select

from app.core.db import get_session
from app.models import PromptSetScope, PromptSetTemplate, PromptSetVersion

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from uuid import UUID


class InternalTemplateLoader(BaseLoader):
    """Prefer `_internal.j2` templates when internal mode is enabled."""

    def __init__(self, template_dir: Path, *, is_internal: bool = False) -> None:
        self.template_dir = template_dir
        self.is_internal = is_internal
        self.fallback_loader = FileSystemLoader(template_dir)

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, Callable[[], bool] | None]:
        if self.is_internal and template.endswith(".j2"):
            if template.endswith("_internal.j2"):
                return self.fallback_loader.get_source(environment, template)

            internal_template = template[:-3] + "_internal.j2"
            return self.fallback_loader.get_source(environment, internal_template)

        return self.fallback_loader.get_source(environment, template)

    def list_templates(self) -> list[str]:
        return self.fallback_loader.list_templates()


class DatabaseOverrideLoader(BaseLoader):
    """Load root prompt templates from DB overrides for the selected prompt set."""

    def __init__(
        self, template_dir: Path, db_templates: dict[str, str], *, is_internal: bool = False
    ) -> None:
        self.template_dir = template_dir
        self.db_templates = db_templates
        self.is_internal = is_internal
        self.fallback_loader = InternalTemplateLoader(template_dir, is_internal=is_internal)

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, Callable[[], bool] | None]:
        if "/" not in template and template.endswith(".j2"):
            if self.is_internal:
                internal_template = (
                    template
                    if template.endswith("_internal.j2")
                    else template[:-3] + "_internal.j2"
                )
                if internal_template in self.db_templates:
                    return self.db_templates[internal_template], None, lambda: False
                return self.fallback_loader.get_source(environment, template)

            if template in self.db_templates:
                return self.db_templates[template], None, lambda: False
            return self.fallback_loader.get_source(environment, template)

        return self.fallback_loader.get_source(environment, template)

    def list_templates(self) -> list[str]:
        disk_templates = set(self.fallback_loader.list_templates())
        db_templates = set(self.db_templates.keys())
        return list(disk_templates | db_templates)


def create_jinja_environment(template_dir: Path, *, is_internal: bool = False) -> Environment:
    return Environment(loader=InternalTemplateLoader(template_dir, is_internal=is_internal))


def create_jinja_environment_with_db(
    template_dir: Path, db_templates: dict[str, str], *, is_internal: bool = False
) -> Environment:
    return Environment(
        loader=DatabaseOverrideLoader(template_dir, db_templates, is_internal=is_internal)
    )


_jinja_environments: dict[tuple[Path, bool], Environment] = {}
_deployed_templates_cache: dict[tuple[bool, PromptSetScope], dict[str, str]] = {}
_version_templates_cache: dict[UUID, dict[str, str]] = {}


def get_jinja_environment(template_dir: Path, *, is_internal: bool = False) -> Environment:
    key = (template_dir, is_internal)
    if key not in _jinja_environments:
        _jinja_environments[key] = create_jinja_environment(template_dir, is_internal=is_internal)
    return _jinja_environments[key]


async def get_deployed_templates(*, is_internal: bool, scope: PromptSetScope) -> dict[str, str]:
    cache_key = (is_internal, scope)
    if cache_key in _deployed_templates_cache:
        return dict(_deployed_templates_cache[cache_key])

    async with get_session() as session:
        version_stmt = (
            select(PromptSetVersion)
            .where(PromptSetVersion.is_deployed == True)  # noqa: E712
            .where(PromptSetVersion.is_internal == is_internal)
            .where(PromptSetVersion.scope == scope)
            .limit(1)
        )
        version = (await session.execute(version_stmt)).scalar_one_or_none()
        if version is None:
            _deployed_templates_cache[cache_key] = {}
            return {}

        templates_stmt = select(PromptSetTemplate).where(
            PromptSetTemplate.prompt_set_version_id == version.id
        )
        prompts = (await session.execute(templates_stmt)).scalars().all()

    templates = {prompt.filename: prompt.content for prompt in prompts}
    _deployed_templates_cache[cache_key] = dict(templates)
    _version_templates_cache[version.id] = dict(templates)
    return templates


async def get_templates_for_version(version_id: UUID) -> dict[str, str]:
    if version_id in _version_templates_cache:
        return dict(_version_templates_cache[version_id])

    async with get_session() as session:
        templates_stmt = select(PromptSetTemplate).where(
            PromptSetTemplate.prompt_set_version_id == version_id
        )
        prompts = (await session.execute(templates_stmt)).scalars().all()

    templates = {prompt.filename: prompt.content for prompt in prompts}
    _version_templates_cache[version_id] = dict(templates)
    return templates


async def get_runtime_jinja_environment(
    template_dir: Path,
    *,
    is_internal: bool = False,
    scope: PromptSetScope = PromptSetScope.ASSISTANT,
    prompt_set_version_id: UUID | None = None,
) -> Environment:
    if prompt_set_version_id is not None:
        db_templates = await get_templates_for_version(prompt_set_version_id)
    else:
        db_templates = await get_deployed_templates(is_internal=is_internal, scope=scope)

    if db_templates:
        return create_jinja_environment_with_db(template_dir, db_templates, is_internal=is_internal)
    return get_jinja_environment(template_dir, is_internal=is_internal)


def clear_deployed_templates_cache() -> None:
    _deployed_templates_cache.clear()
    _version_templates_cache.clear()
    _jinja_environments.clear()
