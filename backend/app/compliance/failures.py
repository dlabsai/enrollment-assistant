from __future__ import annotations

ERROR_MESSAGES = {
    "provider_error": "The screening service could not finish this Chat.",
    "invalid_evidence": (
        "The screening service could not provide verifiable evidence for this Chat."
    ),
    "incomplete": "The screening service could not apply all instructions to this Chat.",
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


def error_message(code: str) -> str:
    return ERROR_MESSAGES.get(code, "This Chat could not be screened. Review it manually.")


def admission_error_message(code: str | None) -> str | None:
    if code is None:
        return None
    return ADMISSION_ERROR_MESSAGES.get(
        code, "This screening could not be started. Start a new screening manually."
    )
