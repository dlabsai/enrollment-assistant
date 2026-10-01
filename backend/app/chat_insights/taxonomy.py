from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

_DATA_DIR = Path(__file__).with_name("data")
_TOPIC_TAXONOMY_PATH = _DATA_DIR / "topic-taxonomy-v2.json"
_DOCUMENT_TAXONOMY_PATH = _DATA_DIR / "document-taxonomy-v1.json"

TOPIC_TAXONOMY_VERSION = 2
DOCUMENT_TAXONOMY_VERSION = 1
CLASSIFIER_VERSION = "3"

REQUEST_TYPES: tuple[str, ...] = (
    "information lookup",
    "eligibility or fit",
    "process or next step",
    "comparison or decision",
    "problem resolution",
    "drafting or script",
    "other",
)


class _TopicItem(BaseModel):
    label: str
    description: str


class _TopicFile(BaseModel):
    topics: list[_TopicItem]


class _DocumentCategoryItem(BaseModel):
    label: str
    definition: str
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class _DocumentFile(BaseModel):
    version: Literal[1]
    status: Literal["exploratory"]
    subject_categories: list[_DocumentCategoryItem]
    document_function_categories: list[_DocumentCategoryItem]
    design_notes: list[str] = Field(default_factory=list)


class _SnapshotItem(BaseModel):
    key: str
    name: str
    description: str
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


_SNAPSHOT_ADAPTER = TypeAdapter(list[_SnapshotItem])


@dataclass(frozen=True)
class CategoryDefinition:
    key: str
    name: str
    description: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "include": list(self.include),
            "exclude": list(self.exclude),
        }


def category_key(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")
    if not normalized:
        raise ValueError("Category label must contain a letter or number")
    return normalized


@cache
def topic_definitions() -> tuple[CategoryDefinition, ...]:
    taxonomy = _TopicFile.model_validate_json(_TOPIC_TAXONOMY_PATH.read_text())
    return tuple(
        CategoryDefinition(
            key=category_key(item.label), name=item.label, description=item.description
        )
        for item in taxonomy.topics
    )


@cache
def _document_file() -> _DocumentFile:
    return _DocumentFile.model_validate_json(_DOCUMENT_TAXONOMY_PATH.read_text())


def _document_definition(item: _DocumentCategoryItem) -> CategoryDefinition:
    return CategoryDefinition(
        key=category_key(item.label),
        name=item.label,
        description=item.definition,
        include=tuple(item.include),
        exclude=tuple(item.exclude),
    )


@cache
def document_subject_definitions() -> tuple[CategoryDefinition, ...]:
    return tuple(_document_definition(item) for item in _document_file().subject_categories)


@cache
def document_function_definitions() -> tuple[CategoryDefinition, ...]:
    return tuple(
        _document_definition(item) for item in _document_file().document_function_categories
    )


def document_taxonomy_guidance() -> tuple[str, ...]:
    return tuple(_document_file().design_notes)


def topic_taxonomy_snapshot(
    definitions: tuple[CategoryDefinition, ...] | None = None,
) -> list[dict[str, object]]:
    return [item.as_dict() for item in definitions or topic_definitions()]


def definitions_from_snapshot(value: object) -> tuple[CategoryDefinition, ...]:
    items = _SNAPSHOT_ADAPTER.validate_python(value)
    return tuple(
        CategoryDefinition(
            key=item.key,
            name=item.name,
            description=item.description,
            include=tuple(item.include),
            exclude=tuple(item.exclude),
        )
        for item in items
    )


def definition_name_map(definitions: tuple[CategoryDefinition, ...]) -> dict[str, str]:
    return {definition.key: definition.name for definition in definitions}
