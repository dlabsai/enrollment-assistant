import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, TypeAdapter

from app.utils import ensure_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_INDENT = 4


def _dump_models_to_json_bytes[T: BaseModel](
    models: Sequence[T], indent: int = DEFAULT_INDENT
) -> bytes:
    return TypeAdapter(Sequence[T]).dump_json(models, indent=indent)


def load_models[T: BaseModel](file_path: Path, model_type: type[T]) -> list[T]:
    return TypeAdapter(list[model_type]).validate_json(file_path.read_bytes())


def save_models[T: BaseModel](
    file_path: Path, models: Sequence[T], indent: int = DEFAULT_INDENT
) -> None:
    ensure_dir(file_path.parent)
    file_path.write_bytes(_dump_models_to_json_bytes(models, indent))
