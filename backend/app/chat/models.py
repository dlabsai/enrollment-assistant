import logging
from collections.abc import Sequence
from datetime import datetime  # noqa: TC003
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from app.utils import ensure_dir

logger = logging.getLogger(__name__)

DEFAULT_INDENT = 4
RAG_DATA_DIR = Path(__file__).parent.parent / "rag" / "data"


def _dump_models_to_json_bytes[T: BaseModel](
    models: Sequence[T], indent: int = DEFAULT_INDENT
) -> bytes:
    return TypeAdapter(Sequence[T]).dump_json(models, indent=indent)


def _load_models[T: BaseModel](file_path: Path, model_type: type[T]) -> list[T]:
    return TypeAdapter(list[model_type]).validate_json(file_path.read_bytes())


def _save_models[T: BaseModel](
    file_path: Path, models: Sequence[T], indent: int = DEFAULT_INDENT
) -> None:
    ensure_dir(file_path.parent)
    file_path.write_bytes(_dump_models_to_json_bytes(models, indent))


class BaseRagModel(BaseModel):
    id: str
    title: str
    url: str
    markdown_content: str
    created: datetime | None = None
    updated: datetime | None = None


class CatalogCourse(BaseRagModel):
    code: str
    credits: str
    description: str
    prerequisites: str | None = None
    prereq_codes: list[str] = []


class CatalogProgram(BaseRagModel):
    school: str | None = None
    courses: dict[str, list[str]] = {}


class CatalogPage(BaseRagModel):
    pass


class WebsitePage(BaseRagModel):
    excerpt: str | None = None
    breadcrumbs: list[dict[str, str | int]] = []


class WebsiteProgram(BaseRagModel):
    excerpt: str | None = None
    breadcrumbs: list[dict[str, str | int]] = []


class TrainingMaterial(BaseRagModel):
    source_path: str
    file_name: str
    file_extension: str
    content_hash: str | None = None


_filename_map: dict[type[BaseModel], str] = {
    CatalogProgram: "catalog_programs.json",
    CatalogCourse: "catalog_courses.json",
    CatalogPage: "catalog_pages.json",
    WebsitePage: "website_pages.json",
    WebsiteProgram: "website_programs.json",
    TrainingMaterial: "training_materials.json",
}


def _load_mapped_models[T: BaseModel](model_type: type[T]) -> list[T]:
    return _load_models(RAG_DATA_DIR / _filename_map[model_type], model_type=model_type)


def load_catalog_programs() -> list[CatalogProgram]:
    return _load_mapped_models(CatalogProgram)


def load_catalog_courses() -> list[CatalogCourse]:
    return _load_mapped_models(CatalogCourse)


def load_catalog_pages() -> list[CatalogPage]:
    return _load_mapped_models(CatalogPage)


def load_website_pages() -> list[WebsitePage]:
    return _load_mapped_models(WebsitePage)


def load_website_programs() -> list[WebsiteProgram]:
    return _load_mapped_models(WebsiteProgram)


def load_training_materials() -> list[TrainingMaterial]:
    path = RAG_DATA_DIR / _filename_map[TrainingMaterial]
    if not path.exists():
        return []
    return _load_models(path, model_type=TrainingMaterial)


def save_models(models: Sequence[BaseModel]) -> None:
    _save_models(RAG_DATA_DIR / _filename_map[type(models[0])], models)
