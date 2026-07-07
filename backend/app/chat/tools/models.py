from datetime import datetime  # noqa: TC003

from pydantic import BaseModel

from app.models import DocumentType


class Document(BaseModel):
    type: DocumentType
    id: int
    title: str
    url: str
    content: str
    updated_at: datetime | None = None


class NotFoundIds(BaseModel):
    not_found_website_page: list[int] = []
    not_found_website_program: list[int] = []
    not_found_catalog_page: list[int] = []
    not_found_catalog_program: list[int] = []
    not_found_catalog_course: list[int] = []
    not_found_training_material: list[int] = []


class TruncatedDocInfo(BaseModel):
    truncated_docs: list[tuple[DocumentType, int, str]] = []  # (type, id, title)
    omitted_docs: list[tuple[DocumentType, int, str]] = []  # (type, id, title)


class DocumentChunkResult(BaseModel):
    type: DocumentType
    id: int
    title: str
    sequence_number: int
    content: str


class FindDocumentChunksResultItem(BaseModel):
    content: str
    sources: dict[str, list[tuple[int, list[int], str]]]


class FindDocumentChunksDedupeSummary(BaseModel):
    effective_limit: int
    candidate_count: int
    unique_candidates: int
    unique_results: int
    candidate_collapsed_occurrences: int
    returned_collapsed_occurrences: int
    omitted_candidate_collapsed_occurrences: int


class DocumentTitleResult(BaseModel):
    type: DocumentType
    id: int
    title: str


class CatalogDocumentResult(BaseModel):
    type: DocumentType
    id: int
    title: str


class CatalogProgramCoursesResult(BaseModel):
    program: CatalogDocumentResult
    courses: list[CatalogDocumentResult]
    unmatched_course_references: list[str] = []
