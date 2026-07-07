import json
from typing import Any

import pytest

from app.chat import inspect as chat_inspect


def test_normalise_tool_invocations_pairs_openai_style_tool_messages() -> None:
    messages: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "find_document_chunks",
                        "arguments": json.dumps(
                            {
                                "content_search_query": "admissions checklist",
                                "document_types": ["training_material"],
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "find_document_chunks",
            "content": json.dumps([{"type": "training_material", "id": -1}]),
        },
    ]

    invocations = chat_inspect._normalise_tool_invocations(messages)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert invocations == [
        {
            "id": "call-1",
            "name": "find_document_chunks",
            "arguments": {
                "content_search_query": "admissions checklist",
                "document_types": ["training_material"],
            },
            "result": {
                "kind": "json_list",
                "count": 1,
                "preview": '[{"type": "training_material", "id": -1}]',
            },
        }
    ]


@pytest.mark.asyncio
async def test_json_output_redirects_runtime_stdout_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_run_ask(_args: object) -> dict[str, Any]:
        print("debug noise from runtime")
        return {
            "conversation_id": "conversation-id",
            "assistant_message_id": "assistant-message-id",
            "response": "hello",
            "guardrails_blocked": False,
            "guardrail_retries": 0,
            "timing": {},
            "models": {},
            "tools": {"count": 0, "message_count": 0, "names": [], "invocations": [], "calls": []},
            "guardrails": None,
            "system_prompt": None,
        }

    monkeypatch.setattr(chat_inspect, "_run_ask", fake_run_ask)

    exit_code = await chat_inspect._main_async(["ask", "--json", "hello"])  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["response"] == "hello"
    assert "debug noise from runtime" not in captured.out
    assert "debug noise from runtime" in captured.err
