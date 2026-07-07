from app.rag.training_materials.urls import (
    training_material_demo_url_from_path,
    training_material_demo_url_from_url,
    training_material_path_from_url,
)


def test_training_material_path_from_url_decodes_synthetic_url() -> None:
    assert (
        training_material_path_from_url(
            "training-materials://Internal%20Advising/Transcript%20Review%20Checklist.md"
        )
        == "Internal Advising/Transcript Review Checklist.md"
    )


def test_training_material_demo_url_encodes_path() -> None:
    assert training_material_demo_url_from_path(
        "Internal Advising/Transcript Review Checklist.md"
    ) == (
        "https://demo-university.example.edu/internal/training-materials/"
        "Internal%20Advising/Transcript%20Review%20Checklist.md"
    )


def test_training_material_demo_url_from_url_decodes_before_encoding() -> None:
    assert training_material_demo_url_from_url(
        "training-materials://Internal%20Advising/Guide%20%26%20Checklist.md"
    ) == (
        "https://demo-university.example.edu/internal/training-materials/"
        "Internal%20Advising/Guide%20%26%20Checklist.md"
    )
