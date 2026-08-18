"""Resolve immutable internal Assistant instructions for an eval run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import TEMPLATES_DIR
from app.models import PromptSetScope, PromptSetTemplate, PromptSetVersion
from app.prompt_sets import (
    get_template_filenames_for_scope,
    hash_prompt_templates,
    read_disk_templates,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

EvalInstructionsSource = Literal["live", "saved", "draft"]

_ASSISTANT_TEMPLATE_FILENAMES = get_template_filenames_for_scope(
    PromptSetScope.ASSISTANT, is_internal=True
)
_ASSISTANT_TEMPLATE_FILENAME_SET = frozenset(_ASSISTANT_TEMPLATE_FILENAMES)


class EvalInstructionsError(ValueError):
    """Base error for an invalid eval instruction selection."""


class EvalInstructionsNotFoundError(EvalInstructionsError):
    """Raised when a selected saved instruction version no longer exists."""


class EvalInstructionsValidationError(EvalInstructionsError):
    """Raised when an instruction selection or template payload is invalid."""


@dataclass(frozen=True)
class _VersionIdentity:
    id: UUID
    version_number: int
    name: str


@dataclass(frozen=True)
class _SavedVersion:
    identity: _VersionIdentity
    templates: dict[str, str]


@dataclass(frozen=True)
class EvalInstructionsSnapshot:
    """Complete internal Assistant templates and identity for one eval run."""

    source: EvalInstructionsSource
    templates: tuple[tuple[str, str], ...]
    content_hash: str
    version: _VersionIdentity | None = None
    base_version: _VersionIdentity | None = None

    @property
    def template_overrides(self) -> dict[str, str]:
        return dict(self.templates)

    @property
    def display_name(self) -> str:
        if self.source == "draft":
            if self.base_version is not None:
                return (
                    "Unsaved draft instructions "
                    f"(based on v{self.base_version.version_number} - "
                    f"{self.base_version.name})"
                )
            return "Unsaved draft instructions (based on default instructions)"
        if self.version is not None:
            prefix = "Live" if self.source == "live" else "Saved"
            return f"{prefix} instructions (v{self.version.version_number} - {self.version.name})"
        return "Live instructions (default instructions)"

    def prompt_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "source": self.source,
            "scope": PromptSetScope.ASSISTANT.value,
            "is_internal": True,
            "hash": self.content_hash,
            "template_filenames": [filename for filename, _content in self.templates],
        }
        version = self.version or self.base_version
        if version is not None:
            context["prompt_set_version_id"] = str(version.id)
        return context

    def report_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {"source": self.source, "hash": self.content_hash}
        if self.version is not None:
            metadata.update(
                {
                    "version_id": str(self.version.id),
                    "version_number": self.version.version_number,
                    "version_name": self.version.name,
                }
            )
        if self.source == "draft":
            metadata["base"] = "saved" if self.base_version is not None else "default"
            if self.base_version is not None:
                metadata.update(
                    {
                        "base_version_id": str(self.base_version.id),
                        "base_version_number": self.base_version.version_number,
                        "base_version_name": self.base_version.name,
                    }
                )
        return metadata


def _validate_complete_templates(templates: dict[str, str], *, source: str) -> None:
    actual = set(templates)
    missing = sorted(_ASSISTANT_TEMPLATE_FILENAME_SET - actual)
    extra = sorted(actual - _ASSISTANT_TEMPLATE_FILENAME_SET)
    if missing:
        raise EvalInstructionsValidationError(
            f"Missing {source} instruction templates: {', '.join(missing)}"
        )
    if extra:
        raise EvalInstructionsValidationError(
            f"Unexpected {source} instruction templates: {', '.join(extra)}"
        )


def _default_templates() -> dict[str, str]:
    disk_templates = read_disk_templates(TEMPLATES_DIR)
    templates = {
        filename: disk_templates[filename]
        for filename in _ASSISTANT_TEMPLATE_FILENAMES
        if filename in disk_templates
    }
    _validate_complete_templates(templates, source="default")
    return templates


def _snapshot(
    *,
    source: EvalInstructionsSource,
    templates: dict[str, str],
    version: _SavedVersion | None = None,
    base_version: _SavedVersion | None = None,
) -> EvalInstructionsSnapshot:
    return EvalInstructionsSnapshot(
        source=source,
        templates=tuple(sorted(templates.items())),
        content_hash=hash_prompt_templates(templates),
        version=version.identity if version is not None else None,
        base_version=base_version.identity if base_version is not None else None,
    )


async def _load_saved_version(session: AsyncSession, version_id: UUID) -> _SavedVersion:
    version = await session.scalar(
        select(PromptSetVersion)
        .where(PromptSetVersion.id == version_id)
        .where(PromptSetVersion.is_internal.is_(True))
        .where(PromptSetVersion.scope == PromptSetScope.ASSISTANT)
    )
    if version is None:
        raise EvalInstructionsNotFoundError("Saved instruction version not found")

    prompts = (
        await session.scalars(
            select(PromptSetTemplate).where(PromptSetTemplate.prompt_set_version_id == version.id)
        )
    ).all()
    templates = {prompt.filename: prompt.content for prompt in prompts}
    _validate_complete_templates(templates, source="saved")
    return _SavedVersion(
        identity=_VersionIdentity(
            id=version.id, version_number=version.version_number, name=version.name
        ),
        templates=templates,
    )


async def _load_live_version(session: AsyncSession) -> _SavedVersion | None:
    version_id = await session.scalar(
        select(PromptSetVersion.id)
        .where(PromptSetVersion.is_internal.is_(True))
        .where(PromptSetVersion.scope == PromptSetScope.ASSISTANT)
        .where(PromptSetVersion.is_deployed.is_(True))
        .order_by(desc(PromptSetVersion.version_number), desc(PromptSetVersion.created_at))
        .limit(1)
    )
    return None if version_id is None else await _load_saved_version(session, version_id)


def _normalize_draft_templates(draft_templates: Iterable[tuple[str, str]] | None) -> dict[str, str]:
    templates: dict[str, str] = {}
    for raw_filename, content in draft_templates or ():
        filename = raw_filename.strip()
        if filename in templates:
            raise EvalInstructionsValidationError(
                f"Duplicate draft instruction template: {filename}"
            )
        templates[filename] = content

    if not templates:
        raise EvalInstructionsValidationError(
            "Unsaved draft instructions require at least one modified template"
        )

    unexpected = sorted(set(templates) - _ASSISTANT_TEMPLATE_FILENAME_SET)
    if unexpected:
        raise EvalInstructionsValidationError(
            f"Unexpected draft instruction templates: {', '.join(unexpected)}"
        )
    return templates


async def resolve_eval_instructions(
    session: AsyncSession,
    *,
    source: EvalInstructionsSource,
    prompt_set_version_id: UUID | None,
    draft_base_prompt_set_version_id: UUID | None,
    draft_templates: Iterable[tuple[str, str]] | None,
) -> EvalInstructionsSnapshot:
    """Resolve a complete instruction snapshot before a background job starts."""
    if source == "live":
        if (
            prompt_set_version_id is not None
            or draft_base_prompt_set_version_id is not None
            or draft_templates is not None
        ):
            raise EvalInstructionsValidationError(
                "Live instructions cannot include a saved version or draft data"
            )
        live_version = await _load_live_version(session)
        if live_version is None:
            return _snapshot(source="live", templates=_default_templates())
        return _snapshot(source="live", templates=live_version.templates, version=live_version)

    if source == "saved":
        if prompt_set_version_id is None:
            raise EvalInstructionsValidationError("A saved instruction version must be selected")
        if draft_base_prompt_set_version_id is not None or draft_templates is not None:
            raise EvalInstructionsValidationError("Saved instructions cannot include draft data")
        version = await _load_saved_version(session, prompt_set_version_id)
        return _snapshot(source="saved", templates=version.templates, version=version)

    if source != "draft":
        raise EvalInstructionsValidationError(f"Unsupported instruction source: {source}")
    if prompt_set_version_id is not None:
        raise EvalInstructionsValidationError(
            "Unsaved draft instructions cannot also select a saved version"
        )

    edits = _normalize_draft_templates(draft_templates)
    base_version = (
        await _load_saved_version(session, draft_base_prompt_set_version_id)
        if draft_base_prompt_set_version_id is not None
        else None
    )
    templates = dict(base_version.templates) if base_version is not None else _default_templates()
    templates.update(edits)
    return _snapshot(source="draft", templates=templates, base_version=base_version)
