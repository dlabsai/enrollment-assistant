"""PydanticAI-only LLM latency benchmark CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings as PydanticModelSettings

from app.chat.agents import get_pydantic_ai_model_name
from app.core.config import settings

DEFAULT_MESSAGE = "Reply with exactly: pong"


class CliError(Exception):
    """Expected CLI failure with a stable exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class TrialResult:
    model: str
    index: int
    elapsed_seconds: float
    output: str
    input_tokens: int | None
    output_tokens: int | None
    requests: int
    usage_details: dict[str, Any]


@dataclass(frozen=True)
class ModelSummary:
    model: str
    requests: int
    average_seconds: float
    median_seconds: float
    minimum_seconds: float
    maximum_seconds: float
    p90_seconds: float
    input_tokens_average: float | None
    output_tokens_average: float | None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.chat.llm_benchmark",
        description=(
            "Measure raw PydanticAI model latency with no system prompt, tools, "
            "database, RAG, guardrails, or handle_conversation_turn."
        ),
    )
    parser.add_argument("--version", action="version", version="app.chat.llm_benchmark 0.1")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help=(
            "model to benchmark; repeat for multiple models. Use 'all' to benchmark "
            "settings.MODELS plus configured role models. Defaults to CHATBOT_MODEL."
        ),
    )
    parser.add_argument(
        "--requests", type=_positive_int, default=5, help="requests per model; default: 5"
    )
    parser.add_argument(
        "--message",
        default=DEFAULT_MESSAGE,
        help=f"user message to send; default: {DEFAULT_MESSAGE!r}",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="optional temperature override passed to PydanticAI model_settings",
    )
    parser.add_argument(
        "--max-tokens",
        type=_non_negative_int,
        default=None,
        help="optional max_tokens override; 0 means omit the override",
    )
    parser.add_argument(
        "--warmup",
        type=_non_negative_int,
        default=0,
        help="warmup requests per model excluded from statistics; default: 0",
    )
    parser.add_argument(
        "--json", action="store_true", help="write JSON instead of human-readable output"
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _configured_models() -> list[str]:
    configured = [
        item.strip()
        for item in settings.MODELS.split(",")
        if item.strip() and "*" not in item.strip()
    ]
    role_models = [
        settings.CHATBOT_MODEL,
        settings.GUARDRAIL_MODEL,
        settings.EVALUATION_MODEL,
        settings.SUMMARIZER_MODEL,
    ]
    return _dedupe([*configured, *role_models])


def resolve_models(values: Sequence[str] | None) -> list[str]:
    if not values:
        return [settings.CHATBOT_MODEL]

    expanded: list[str] = []
    for value in values:
        for item in value.split(","):
            model = item.strip()
            if not model:
                continue
            if model == "all":
                expanded.extend(_configured_models())
            else:
                expanded.append(model)

    models = _dedupe(expanded)
    if not models:
        raise CliError("at least one model is required", exit_code=2)
    return models


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def model_settings(
    *, temperature: float | None, max_tokens: int | None
) -> PydanticModelSettings | None:
    payload: PydanticModelSettings = {}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None and max_tokens != 0:
        payload["max_tokens"] = max_tokens
    return payload or None


async def _run_one(
    *,
    agent: Agent[None, str],
    model: str,
    index: int,
    message: str,
    model_settings: PydanticModelSettings | None,
) -> TrialResult:
    start = time.perf_counter()
    result = await agent.run(message, model_settings=model_settings)
    elapsed = time.perf_counter() - start
    usage = result.usage()
    return TrialResult(
        model=model,
        index=index,
        elapsed_seconds=elapsed,
        output=result.output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        usage_details=dict(usage.details or {}),
    )


async def _benchmark_model(
    *,
    model: str,
    requests: int,
    warmup: int,
    message: str,
    model_settings: PydanticModelSettings | None,
) -> list[TrialResult]:
    agent = Agent(get_pydantic_ai_model_name(model), output_type=str, system_prompt="")

    for warmup_index in range(1, warmup + 1):
        await _run_one(
            agent=agent,
            model=model,
            index=-warmup_index,
            message=message,
            model_settings=model_settings,
        )

    results: list[TrialResult] = []
    for index in range(1, requests + 1):
        results.append(
            await _run_one(
                agent=agent,
                model=model,
                index=index,
                message=message,
                model_settings=model_settings,
            )
        )
    return results


def summarize_trials(model: str, trials: Sequence[TrialResult]) -> ModelSummary:
    if not trials:
        raise ValueError("cannot summarize empty trial list")

    elapsed = [trial.elapsed_seconds for trial in trials]
    input_tokens = [trial.input_tokens for trial in trials if trial.input_tokens is not None]
    output_tokens = [trial.output_tokens for trial in trials if trial.output_tokens is not None]
    return ModelSummary(
        model=model,
        requests=len(trials),
        average_seconds=statistics.mean(elapsed),
        median_seconds=statistics.median(elapsed),
        minimum_seconds=min(elapsed),
        maximum_seconds=max(elapsed),
        p90_seconds=_percentile(elapsed, 0.9),
        input_tokens_average=statistics.mean(input_tokens) if input_tokens else None,
        output_tokens_average=statistics.mean(output_tokens) if output_tokens else None,
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile for empty values")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _trial_payload(trial: TrialResult) -> dict[str, Any]:
    return {
        "model": trial.model,
        "index": trial.index,
        "elapsed_seconds": trial.elapsed_seconds,
        "output": trial.output,
        "input_tokens": trial.input_tokens,
        "output_tokens": trial.output_tokens,
        "requests": trial.requests,
        "usage_details": trial.usage_details,
    }


def _summary_payload(summary: ModelSummary) -> dict[str, Any]:
    return {
        "model": summary.model,
        "requests": summary.requests,
        "average_seconds": summary.average_seconds,
        "median_seconds": summary.median_seconds,
        "minimum_seconds": summary.minimum_seconds,
        "maximum_seconds": summary.maximum_seconds,
        "p90_seconds": summary.p90_seconds,
        "input_tokens_average": summary.input_tokens_average,
        "output_tokens_average": summary.output_tokens_average,
    }


def _print_human(summaries: Sequence[ModelSummary], trials: Sequence[TrialResult]) -> None:
    print("PydanticAI latency baseline")
    print("No system prompt, no tools, no DB, no guardrails, no handle_conversation_turn.\n")
    for summary in summaries:
        print(
            f"{summary.model}: avg={summary.average_seconds:.3f}s "
            f"med={summary.median_seconds:.3f}s p90={summary.p90_seconds:.3f}s "
            f"min={summary.minimum_seconds:.3f}s max={summary.maximum_seconds:.3f}s "
            f"n={summary.requests}"
        )
        model_trials = [trial for trial in trials if trial.model == summary.model]
        for trial in model_trials:
            print(
                f"  #{trial.index}: {trial.elapsed_seconds:.3f}s "
                f"in={trial.input_tokens} out={trial.output_tokens} output={trial.output!r}"
            )
        print()


async def _main_async(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        models = resolve_models(cast(Sequence[str] | None, args.models))
        model_settings_payload = model_settings(
            temperature=cast(float | None, args.temperature),
            max_tokens=cast(int | None, args.max_tokens),
        )
        all_trials: list[TrialResult] = []
        summaries: list[ModelSummary] = []
        for model in models:
            trials = await _benchmark_model(
                model=model,
                requests=cast(int, args.requests),
                warmup=cast(int, args.warmup),
                message=cast(str, args.message),
                model_settings=model_settings_payload,
            )
            all_trials.extend(trials)
            summaries.append(summarize_trials(model, trials))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if cast(bool, args.json):
        print(
            json.dumps(
                {
                    "message": args.message,
                    "models": models,
                    "summaries": [_summary_payload(summary) for summary in summaries],
                    "trials": [_trial_payload(trial) for trial in all_trials],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_human(summaries, all_trials)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
