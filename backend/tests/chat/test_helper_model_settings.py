from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai.messages import TextPart

from app.chat import internal_summary, title


class _FakeTemplate:
    def render(self, **_: object) -> str:
        return "rendered prompt"


class _FakeEnvironment:
    def get_template(self, _name: str) -> _FakeTemplate:
        return _FakeTemplate()


async def _fake_environment(*_: Any, **__: Any) -> _FakeEnvironment:
    return _FakeEnvironment()


def _ignore_response_attributes(*_: Any, **__: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_title_request_uses_configured_output_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_settings: list[object] = []

    async def fake_model_request(*_: Any, **kwargs: Any) -> SimpleNamespace:
        captured_settings.append(kwargs.get("model_settings"))
        return SimpleNamespace(parts=[TextPart(content="Generated title")])

    monkeypatch.setattr(title.settings, "TITLE_MODEL_MAX_TOKENS", 123)
    monkeypatch.setattr(title, "model_request", fake_model_request)
    monkeypatch.setattr(
        title, "set_direct_model_response_span_attributes", _ignore_response_attributes
    )
    monkeypatch.setattr(title, "get_runtime_jinja_environment", _fake_environment)

    result = await title.generate_conversation_title("Title this")

    assert result == "Generated title"
    assert captured_settings == [{"max_tokens": 123}]


@pytest.mark.asyncio
async def test_summary_requests_use_configured_output_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_settings: list[object] = []

    async def fake_model_request(*_: Any, **kwargs: Any) -> SimpleNamespace:
        captured_settings.append(kwargs.get("model_settings"))
        return SimpleNamespace(parts=[TextPart(content="Generated summary")])

    monkeypatch.setattr(internal_summary.settings, "SUMMARIZER_MODEL_MAX_TOKENS", 456)
    monkeypatch.setattr(internal_summary, "model_request", fake_model_request)
    monkeypatch.setattr(
        internal_summary, "set_direct_model_response_span_attributes", _ignore_response_attributes
    )
    monkeypatch.setattr(internal_summary, "get_runtime_jinja_environment", _fake_environment)
    internal_result = await internal_summary._generate_internal_summary(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        "Internal transcript", conversation_id=uuid4(), trigger_message_id=None
    )

    assert internal_result == "Generated summary"
    assert captured_settings == [{"max_tokens": 456}]
