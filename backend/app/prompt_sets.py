import collections.abc  # noqa: TC003
import pathlib  # noqa: TC003
from dataclasses import dataclass

from app.models import PromptSetScope

_SCOPE_TEMPLATE_BASES: dict[PromptSetScope, tuple[str, ...]] = {
    PromptSetScope.ASSISTANT: ("chatbot_agent", "guardrails_agent"),
    PromptSetScope.INVESTIGATION: ("investigation_agent",),
    PromptSetScope.SUMMARY: ("summary_agent",),
    PromptSetScope.TITLE: ("title_agent",),
    PromptSetScope.TITLE_TRANSCRIPT: ("title_agent_transcript",),
    PromptSetScope.GROUNDING: ("grounding_agent",),
}


@dataclass(frozen=True)
class PromptSetDescriptor:
    scope: PromptSetScope
    is_internal: bool
    filenames: tuple[str, ...]


def _filename_for_base(base: str, *, is_internal: bool) -> str:
    return f"{base}_internal.j2" if is_internal else f"{base}.j2"


def get_template_filenames_for_scope(
    scope: PromptSetScope, *, is_internal: bool
) -> tuple[str, ...]:
    return tuple(
        _filename_for_base(base, is_internal=is_internal) for base in _SCOPE_TEMPLATE_BASES[scope]
    )


PROMPT_SET_DESCRIPTORS: tuple[PromptSetDescriptor, ...] = tuple(
    PromptSetDescriptor(
        scope=scope,
        is_internal=is_internal,
        filenames=get_template_filenames_for_scope(scope, is_internal=is_internal),
    )
    for scope in PromptSetScope
    for is_internal in (False, True)
)

_PROMPT_SET_DESCRIPTOR_BY_FILENAMES: dict[frozenset[str], PromptSetDescriptor] = {
    frozenset(descriptor.filenames): descriptor for descriptor in PROMPT_SET_DESCRIPTORS
}


def classify_prompt_set(filenames: collections.abc.Iterable[str]) -> PromptSetDescriptor | None:
    normalized = frozenset(filename.strip() for filename in filenames if filename.strip() != "")
    if not normalized:
        return None
    return _PROMPT_SET_DESCRIPTOR_BY_FILENAMES.get(normalized)


def read_disk_templates(template_dir: pathlib.Path) -> dict[str, str]:
    return {
        file_path.name: file_path.read_text()
        for file_path in template_dir.glob("*.j2")
        if file_path.is_file()
    }
