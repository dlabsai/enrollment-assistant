import pytest

from app.chat import llm_benchmark


def test_resolve_models_defaults_to_chatbot_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_benchmark.settings, "CHATBOT_MODEL", "azure/default")

    assert llm_benchmark.resolve_models(None) == ["azure/default"]


def test_resolve_models_expands_all_and_dedupes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_benchmark.settings, "MODELS", "azure/a,azure/b,openrouter/*,")
    monkeypatch.setattr(llm_benchmark.settings, "CHATBOT_MODEL", "azure/b")
    monkeypatch.setattr(llm_benchmark.settings, "GUARDRAIL_MODEL", "azure/c")
    monkeypatch.setattr(llm_benchmark.settings, "EVALUATION_MODEL", "azure/d")
    monkeypatch.setattr(llm_benchmark.settings, "SUMMARIZER_MODEL", "azure/e")

    assert llm_benchmark.resolve_models(["all", "azure/a", "azure/f"]) == [
        "azure/a",
        "azure/b",
        "azure/c",
        "azure/d",
        "azure/e",
        "azure/f",
    ]


def test_summarize_trials_uses_current_trials_only():
    trials = [
        llm_benchmark.TrialResult(
            model="azure/test",
            index=1,
            elapsed_seconds=1.0,
            output="pong",
            input_tokens=10,
            output_tokens=2,
            requests=1,
            usage_details={},
        ),
        llm_benchmark.TrialResult(
            model="azure/test",
            index=2,
            elapsed_seconds=3.0,
            output="pong",
            input_tokens=20,
            output_tokens=4,
            requests=1,
            usage_details={},
        ),
    ]

    summary = llm_benchmark.summarize_trials("azure/test", trials)

    assert summary.average_seconds == 2.0
    assert summary.median_seconds == 2.0
    assert summary.minimum_seconds == 1.0
    assert summary.maximum_seconds == 3.0
    assert summary.p90_seconds == 3.0
    assert summary.input_tokens_average == 15.0
    assert summary.output_tokens_average == 3.0


def test_model_settings_omits_zero_max_tokens():
    assert llm_benchmark.model_settings(temperature=None, max_tokens=0) is None
    assert llm_benchmark.model_settings(temperature=0.2, max_tokens=10) == {
        "temperature": 0.2,
        "max_tokens": 10,
    }
