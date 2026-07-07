from app.models import DocumentType
from app.rag.source_keys import document_source_key


def test_training_material_source_key_preserves_literal_hash_in_filename() -> None:
    url = (
        "training-materials://Internal%20Advising/"
        "New%20%20Unconverted%20Leads%20#4%20-%20approved.md"
    )

    assert document_source_key(DocumentType.TRAINING_MATERIAL, -1, "title", url, "") == (
        "training_material:Internal Advising/New  Unconverted Leads #4 - approved.md"
    )


def test_training_material_source_keys_distinguish_hash_numbered_files() -> None:
    base_url = "training-materials://Internal%20Advising/"

    first_key = document_source_key(
        DocumentType.TRAINING_MATERIAL,
        -1,
        "title",
        f"{base_url}New%20%20Unconverted%20Leads%20#1%20-%20approved.md",
        "",
    )
    fourth_key = document_source_key(
        DocumentType.TRAINING_MATERIAL,
        -2,
        "title",
        f"{base_url}New%20%20Unconverted%20Leads%20#4%20-%20approved.md",
        "",
    )

    assert first_key != fourth_key


def test_website_page_source_key_uses_document_type_and_source_id() -> None:
    assert (
        document_source_key(
            DocumentType.WEBSITE_PAGE,
            1001,
            "Admissions",
            "https://demo-university.example.edu/admissions/",
            "# Admissions\n",
        )
        == "website_page:1001"
    )
