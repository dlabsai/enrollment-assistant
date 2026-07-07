from __future__ import annotations

from typing import Final

INTERNAL_PROMPT_ALLOWED_URLS: Final[tuple[str, ...]] = (
    "https://apply.demo-university.example.edu/",
    "https://demo-university.example.edu/accreditation-and-consumer-information/",
    "https://catalog.demo-university.example.edu/",
    "https://studentaid.gov",
    "https://www.bls.gov/ooh/",
)

PUBLIC_PROMPT_ALLOWED_URLS: Final[tuple[str, ...]] = (
    "https://apply.demo-university.example.edu/",
    "https://demo-university.example.edu/accreditation-and-consumer-information/",
    "https://catalog.demo-university.example.edu/",
    "https://studentaid.gov",
    "https://www.bls.gov/ooh/",
)


def get_prompt_allowed_urls(*, is_internal: bool) -> tuple[str, ...]:
    return INTERNAL_PROMPT_ALLOWED_URLS if is_internal else PUBLIC_PROMPT_ALLOWED_URLS
