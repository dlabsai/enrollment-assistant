from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from app.rag.json_io import save_models
from app.rag.models import (
    CatalogCourse,
    CatalogPage,
    CatalogProgram,
    TrainingMaterial,
    WebsitePage,
    WebsiteProgram,
)
from app.rag.utils import DATA_DIR

_DEMO_CORPUS_DIR = Path(__file__).parent
_WEBSITE_PAGES_DIR = _DEMO_CORPUS_DIR / "website" / "pages"
_WEBSITE_PROGRAMS_DIR = _DEMO_CORPUS_DIR / "website" / "programs"
_CATALOG_PAGES_DIR = _DEMO_CORPUS_DIR / "catalog" / "pages"
_CATALOG_PROGRAMS_DIR = _DEMO_CORPUS_DIR / "catalog" / "programs"
_CATALOG_COURSES_DIR = _DEMO_CORPUS_DIR / "catalog" / "courses"
_TRAINING_MATERIALS_DIR = _DEMO_CORPUS_DIR / "training_materials"
_GENERATED_AT = datetime(2026, 1, 15, tzinfo=UTC)
_WEBSITE_BASE_URL = "https://demo-university.example.edu"
_CATALOG_BASE_URL = "https://catalog.demo-university.example.edu"
_COURSE_CODE_PATTERN = re.compile(r"\b[A-Z]{2,4}\s+\d{3}[A-Z0-9]*\b")
_FIELD_PATTERN_TEMPLATE = r"^\*\*{label}:\*\*\s*(?P<value>.+?)\s*$"


@dataclass(frozen=True)
class DemoCorpusStats:
    website_pages: int
    website_programs: int
    catalog_pages: int
    catalog_programs: int
    catalog_courses: int
    training_materials: int

    @property
    def total_documents(self) -> int:
        return (
            self.website_pages
            + self.website_programs
            + self.catalog_pages
            + self.catalog_programs
            + self.catalog_courses
            + self.training_materials
        )


def _read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() + "\n"


def _markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback.replace("-", " ").title()


def _markdown_excerpt(markdown: str) -> str | None:
    for block in markdown.split("\n\n"):
        stripped = block.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("**"):
            return stripped.replace("\n", " ")[:500]
    return None


def _field(markdown: str, label: str) -> str | None:
    pattern = re.compile(
        _FIELD_PATTERN_TEMPLATE.format(label=re.escape(label)), re.IGNORECASE | re.MULTILINE
    )
    match = pattern.search(markdown)
    return match.group("value").strip() if match else None


def _content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _page_url(slug: str) -> str:
    return f"{_WEBSITE_BASE_URL}/" if slug == "home" else f"{_WEBSITE_BASE_URL}/{slug}/"


def _website_program_url(slug: str) -> str:
    return f"{_WEBSITE_BASE_URL}/programs/{slug}/"


def _catalog_program_url(slug: str) -> str:
    return f"{_CATALOG_BASE_URL}/programs/{slug}"


def _catalog_course_url(slug: str) -> str:
    return f"{_CATALOG_BASE_URL}/courses/{slug}"


def _training_material_url(relative_path: str) -> str:
    return "training-materials://" + quote(relative_path, safe="/")


def _load_website_pages() -> list[WebsitePage]:
    pages: list[WebsitePage] = []
    for index, path in enumerate(sorted(_WEBSITE_PAGES_DIR.glob("*.md")), start=1001):
        slug = path.stem
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=slug)
        pages.append(
            WebsitePage(
                id=str(index),
                title=title,
                url=_page_url(slug),
                markdown_content=markdown,
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
                excerpt=_markdown_excerpt(markdown),
                breadcrumbs=[{"title": "Home", "url": _WEBSITE_BASE_URL}],
            )
        )
    return pages


def _load_website_programs() -> list[WebsiteProgram]:
    programs: list[WebsiteProgram] = []
    for index, path in enumerate(sorted(_WEBSITE_PROGRAMS_DIR.glob("*.md")), start=2001):
        slug = path.stem
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=slug)
        programs.append(
            WebsiteProgram(
                id=str(index),
                title=title,
                url=_website_program_url(slug),
                markdown_content=markdown,
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
                excerpt=_markdown_excerpt(markdown),
                breadcrumbs=[
                    {"title": "Home", "url": _WEBSITE_BASE_URL},
                    {
                        "title": "Academic Programs",
                        "url": f"{_WEBSITE_BASE_URL}/academic-programs/",
                    },
                ],
            )
        )
    return programs


def _extract_program_courses(markdown: str) -> dict[str, list[str]]:
    courses: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        match = _COURSE_CODE_PATTERN.search(stripped)
        if match:
            courses.append(match.group(0))
    return {"Core": courses} if courses else {}


def _load_catalog_pages() -> list[CatalogPage]:
    pages: list[CatalogPage] = []
    for index, path in enumerate(sorted(_CATALOG_PAGES_DIR.glob("*.md")), start=5001):
        slug = path.stem
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=slug)
        pages.append(
            CatalogPage(
                id=str(index),
                title=title,
                url=f"{_CATALOG_BASE_URL}/{slug}",
                markdown_content=markdown,
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
            )
        )
    return pages


def _load_catalog_programs() -> list[CatalogProgram]:
    programs: list[CatalogProgram] = []
    for index, path in enumerate(sorted(_CATALOG_PROGRAMS_DIR.glob("*.md")), start=6001):
        slug = path.stem
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=slug)
        programs.append(
            CatalogProgram(
                id=str(index),
                title=title,
                url=_catalog_program_url(slug),
                markdown_content=markdown,
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
                school=_field(markdown, "School"),
                courses=_extract_program_courses(markdown),
            )
        )
    return programs


def _course_code_from_markdown(title: str, markdown: str) -> str:
    explicit_code = _field(markdown, "Code")
    if explicit_code:
        return explicit_code
    match = _COURSE_CODE_PATTERN.search(title)
    return match.group(0) if match else title.partition(" - ")[0].strip()


def _course_description(markdown: str) -> str:
    explicit_description = _field(markdown, "Description")
    if explicit_description:
        return explicit_description
    excerpt = _markdown_excerpt(markdown)
    return excerpt or ""


def _load_catalog_courses() -> list[CatalogCourse]:
    courses: list[CatalogCourse] = []
    for index, path in enumerate(sorted(_CATALOG_COURSES_DIR.glob("*.md")), start=7001):
        slug = path.stem
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=slug)
        code = _course_code_from_markdown(title, markdown)
        courses.append(
            CatalogCourse(
                id=str(index),
                title=title,
                url=_catalog_course_url(slug),
                markdown_content=markdown,
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
                code=code,
                credits=_field(markdown, "Credits") or "",
                description=_course_description(markdown),
            )
        )
    return courses


def _load_training_materials() -> list[TrainingMaterial]:
    materials: list[TrainingMaterial] = []
    for index, path in enumerate(sorted(_TRAINING_MATERIALS_DIR.rglob("*.md")), start=1):
        markdown = _read_markdown(path)
        title = _markdown_title(markdown, fallback=path.stem)
        relative_path = path.relative_to(_TRAINING_MATERIALS_DIR).as_posix()
        if "/" not in relative_path:
            relative_path = f"Internal Advising/{relative_path}"
        materials.append(
            TrainingMaterial(
                id=str(-4000 - index),
                title=title,
                url=_training_material_url(relative_path),
                markdown_content=(
                    markdown.rstrip()
                    + "\n\n---\n"
                    + f"Source path: `{relative_path}`\n"
                    + f"Content hash: `{_content_hash(markdown)}`\n"
                ),
                created=_GENERATED_AT,
                updated=_GENERATED_AT,
                source_path=relative_path,
                file_name=path.name,
                file_extension=path.suffix.lower(),
                content_hash=_content_hash(markdown),
            )
        )
    return materials


def write_demo_rag_data(*, output_dir: Path = DATA_DIR) -> DemoCorpusStats:
    """Write the repo-local Markdown corpus to the RAG source JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    website_pages = _load_website_pages()
    website_programs = _load_website_programs()
    catalog_pages = _load_catalog_pages()
    catalog_programs = _load_catalog_programs()
    catalog_courses = _load_catalog_courses()
    training_materials = _load_training_materials()

    save_models(output_dir / "website_pages.json", website_pages)
    save_models(output_dir / "website_programs.json", website_programs)
    save_models(output_dir / "catalog_pages.json", catalog_pages)
    save_models(output_dir / "catalog_programs.json", catalog_programs)
    save_models(output_dir / "catalog_courses.json", catalog_courses)
    save_models(output_dir / "training_materials.json", training_materials)

    return DemoCorpusStats(
        website_pages=len(website_pages),
        website_programs=len(website_programs),
        catalog_pages=len(catalog_pages),
        catalog_programs=len(catalog_programs),
        catalog_courses=len(catalog_courses),
        training_materials=len(training_materials),
    )


def main() -> None:
    stats = write_demo_rag_data()
    print(
        "Wrote Demo University Markdown RAG corpus: "
        f"{stats.total_documents} documents "
        f"({stats.website_pages} website pages, "
        f"{stats.website_programs} website programs, "
        f"{stats.catalog_programs} catalog programs, "
        f"{stats.catalog_courses} catalog courses, "
        f"{stats.training_materials} training materials)."
    )


if __name__ == "__main__":
    main()
