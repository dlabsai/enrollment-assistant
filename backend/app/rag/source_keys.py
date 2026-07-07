from __future__ import annotations

from app.models import DocumentType
from app.rag.training_materials.urls import training_material_path_from_url


def document_source_key(
    document_type: DocumentType, source_id: int, title: str, url: str, markdown_content: str
) -> str:
    del title, markdown_content
    if document_type == DocumentType.TRAINING_MATERIAL:
        return f"training_material:{training_material_path_from_url(url)}"
    return f"{document_type.value}:{source_id}"
