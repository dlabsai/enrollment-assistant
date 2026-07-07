from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parents[2] / "app" / "chat" / "templates"


def _render(template_name: str, **context: object) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    return env.get_template(template_name).render(**context)


def test_internal_chatbot_prompt_contains_retrieval_and_staff_contract() -> None:
    prompt = _render("chatbot_agent_internal.j2", current_date="Apr 29 2026")

    assert "INTERNAL SOURCE PRIORITY" in prompt
    assert "STAGED RETRIEVAL WORKFLOW FOR SOURCE-GROUNDED QUERIES" in prompt
    assert "find_document_chunks" in prompt
    assert "retrieve_documents" in prompt
    assert "You are an Internal Knowledge Assistant" in prompt


def test_public_chatbot_prompt_contains_retrieval_and_public_response_contract() -> None:
    prompt = _render("chatbot_agent.j2", current_date="Apr 29 2026")

    assert "REQUIRED WORKFLOW FOR EVERY QUERY" in prompt
    assert "find_document_chunks" in prompt
    assert "retrieve_documents" in prompt
    assert "Your tone of voice is:" in prompt
