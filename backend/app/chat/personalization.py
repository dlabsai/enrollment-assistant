"""Literal account preferences passed to internal prompt templates."""

import json

MAX_PERSONAL_INSTRUCTIONS_LENGTH = 2000


def serialize_personal_instructions(personal_instructions: str) -> str:
    """Keep personal text literal; whitespace-only preferences are disabled."""
    return (
        json.dumps(personal_instructions, ensure_ascii=False)
        if personal_instructions.strip()
        else ""
    )
