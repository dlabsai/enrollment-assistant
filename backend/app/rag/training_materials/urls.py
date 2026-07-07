from __future__ import annotations

from urllib.parse import quote, unquote

_TRAINING_MATERIAL_SYNTHETIC_SCHEME = "training-materials://"
_TRAINING_MATERIAL_DEMO_URL_PREFIX = (
    "https://demo-university.example.edu/internal/training-materials/"
)


def training_material_path_from_url(url: str) -> str:
    if not url.startswith(_TRAINING_MATERIAL_SYNTHETIC_SCHEME):
        return url
    return unquote(url.removeprefix(_TRAINING_MATERIAL_SYNTHETIC_SCHEME))


def training_material_demo_url_from_path(relative_path: str) -> str:
    """Return a demo-friendly URL for a synthetic training-material path."""
    normalized_path = relative_path.strip().lstrip("/")
    return _TRAINING_MATERIAL_DEMO_URL_PREFIX + quote(normalized_path, safe="/")


def training_material_demo_url_from_url(url: str) -> str:
    return training_material_demo_url_from_path(training_material_path_from_url(url))
