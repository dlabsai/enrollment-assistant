from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

ERROR_MESSAGES = {
    "provider_error": "The screening service could not finish this Chat.",
    "invalid_evidence": (
        "The screening service could not provide verifiable evidence for this Chat."
    ),
    "incomplete": "The screening service could not apply all instructions to this Chat.",
    "jailbreak_blocked": (
        "Screening stopped because the service thought text in this Chat might be an "
        "attempt to change the screening instructions. Trying the same Chat again is "
        "unlikely to help."
    ),
    "too_long": "This Chat is too long to screen without leaving out context. Review it manually.",
    "missing_display": "Historical assistant-message content is unavailable for this Chat.",
    "invalid_context": (
        "The original Chat context is incomplete. Review the available Chat manually."
    ),
    "access_changed": (
        "The screening requester no longer has access to this Chat. "
        "Restore that access or start a new screening."
    ),
    "worker_interrupted": "Screening was interrupted repeatedly for this Chat.",
    "screening_version_changed": (
        "The screening configuration has changed. Start a new screening for this period."
    ),
}

RETRIABLE_ERROR_CODES = frozenset(
    {"provider_error", "invalid_evidence", "incomplete", "worker_interrupted"}
)

SCHEDULED_TOO_LARGE = "scheduled_too_large"
ADMISSION_ERROR_MESSAGES = {
    SCHEDULED_TOO_LARGE: (
        "Too many assistant messages were eligible for this scheduled screening. "
        "Start separate manual screenings for shorter periods."
    )
}


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)


def is_azure_jailbreak_block(body: object) -> bool:
    if not isinstance(body, str):
        return False
    try:
        payload = json.loads(body)
    except ValueError:
        return False
    if not isinstance(payload, list):
        return False
    responses = cast("list[object]", payload)
    for raw_response in responses:
        response = _as_mapping(raw_response)
        if (
            response is None
            or response.get("provider_name") != "azure"
            or response.get("finish_reason") != "content_filter"
        ):
            continue
        details = _as_mapping(response.get("provider_details"))
        content_filter_result = (
            _as_mapping(details.get("content_filter_result")) if details else None
        )
        jailbreak = (
            _as_mapping(content_filter_result.get("jailbreak")) if content_filter_result else None
        )
        if (
            jailbreak is not None
            and jailbreak.get("detected") is True
            and jailbreak.get("filtered") is True
        ):
            return True
    return False


def error_message(code: str) -> str:
    return ERROR_MESSAGES.get(code, "This Chat could not be screened. Review it manually.")


def admission_error_message(code: str | None) -> str | None:
    if code is None:
        return None
    return ADMISSION_ERROR_MESSAGES.get(
        code, "This screening could not be started. Start a new screening manually."
    )
