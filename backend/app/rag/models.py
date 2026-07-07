import logging
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.rag.json_io import load_models as load_models_
from app.rag.json_io import save_models as save_models_
from app.rag.utils import DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


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
    try:
        return load_models_(DATA_DIR / _filename_map[model_type], model_type=model_type)
    except Exception:
        logger.warning(f"Failed to load models of type {model_type.__name__}", exc_info=True)
        return []


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
    path = DATA_DIR / _filename_map[TrainingMaterial]
    if not path.exists():
        return []
    return load_models_(path, model_type=TrainingMaterial)


def save_models(models: Sequence[BaseModel]) -> None:
    save_models_(DATA_DIR / _filename_map[type(models[0])], models)
