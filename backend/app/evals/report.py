"""Report classes for evaluation results."""

import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

# ANSI color codes
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

# Fields to exclude from report output (e.g., system_prompt is too verbose)
_EXCLUDED_OUTPUT_FIELDS = {"system_prompt", "retrieved_tool_context"}

# Threshold for inline vs code block formatting in markdown
_INLINE_VALUE_MAX_LENGTH = 100


def _fmt_num(value: float, decimals: int = 1) -> str:
    """Format a number, showing as integer if no decimal part."""
    if value == int(value):
        return str(int(value))
    return f"{value:.{decimals}f}"


def _fmt_pct(value: float) -> str:
    """Format a percentage, showing as integer if no decimal part."""
    pct = value * 100
    if pct == int(pct):
        return f"{int(pct)}%"
    return f"{pct:.1f}%"


@dataclass
class EvaluationResult:
    """A single evaluation result.

    Attributes:
        name: Name of the evaluator or result key.
        value: The evaluation value.
        reason: Optional explanation.

    """

    name: str
    value: bool | float | str
    reason: str | None = None


@dataclass
class RunResult[OutputT]:
    """Result of a single task run.

    Attributes:
        output: The task output.
        duration: How long the task took (seconds).
        assertions: Pass/fail results.
        scores: Numeric scores.
        labels: String labels.
        error: Error message if task failed.

    """

    output: OutputT | None
    duration: float
    assertions: dict[str, EvaluationResult] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    scores: dict[str, EvaluationResult] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    labels: dict[str, EvaluationResult] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    error: str | None = None
    otel_trace_id: str | None = None
    otel_span_id: str | None = None


@dataclass
class ReportCaseStats:
    """Statistics for a case run multiple times.

    Attributes:
        runs: Number of runs.
        assertion_pass_rates: Pass rate for each assertion (0.0-1.0).
        score_means: Mean score for each score.
        score_stdevs: Standard deviation for each score.
        score_mins: Minimum value for each score.
        score_medians: Median value for each score.
        score_maxs: Maximum value for each score.
        duration_mean: Mean task duration.
        duration_stdev: Standard deviation of task duration.
        duration_min: Minimum task duration.
        duration_median: Median task duration.
        duration_max: Maximum task duration.
        runtime_error_rate: Fraction of runs with runtime errors.
        pass_rate: Fraction of runs that passed all assertions.

    """

    runs: int
    assertion_pass_rates: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    score_means: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    score_stdevs: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    score_mins: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    score_medians: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    score_maxs: dict[str, float] = field(
        default_factory=lambda: {}  # noqa: PIE807
    )
    duration_mean: float = 0.0
    duration_stdev: float = 0.0
    duration_min: float = 0.0
    duration_median: float = 0.0
    duration_max: float = 0.0
    runtime_error_rate: float = 0.0
    pass_rate: float = 0.0

    @classmethod
    def from_run_results(cls, results: Sequence[RunResult[Any]]) -> ReportCaseStats:
        """Calculate statistics from a list of run results."""
        n = len(results)
        if n == 0:
            return cls(runs=0)

        # Count runtime errors
        runtime_errors = sum(1 for r in results if r.error is not None)

        # Filter successful runs for stats
        successful = [r for r in results if r.error is None]
        if not successful:
            return cls(runs=n, runtime_error_rate=1.0, pass_rate=0.0)

        # Durations
        durations = [r.duration for r in successful]
        duration_mean = statistics.mean(durations)
        duration_stdev = statistics.stdev(durations) if len(durations) > 1 else 0.0
        duration_min = min(durations)
        duration_median = statistics.median(durations)
        duration_max = max(durations)

        # Assertions - calculate pass rate
        assertion_names: set[str] = set()
        for r in successful:
            assertion_names.update(r.assertions.keys())

        assertion_pass_rates: dict[str, float] = {}
        for name in assertion_names:
            passes = sum(
                1 for r in successful if name in r.assertions and r.assertions[name].value is True
            )
            assertion_pass_rates[name] = passes / len(successful)

        # Scores - calculate mean, stdev, min, median, max
        score_names: set[str] = set()
        for r in successful:
            score_names.update(r.scores.keys())

        score_means: dict[str, float] = {}
        score_stdevs: dict[str, float] = {}
        score_mins: dict[str, float] = {}
        score_medians: dict[str, float] = {}
        score_maxs: dict[str, float] = {}
        for name in score_names:
            values: list[float] = [
                float(r.scores[name].value)
                for r in successful
                if name in r.scores and isinstance(r.scores[name].value, (int, float))
            ]
            if values:
                score_means[name] = statistics.mean(values)
                score_stdevs[name] = statistics.stdev(values) if len(values) > 1 else 0.0
                score_mins[name] = min(values)
                score_medians[name] = statistics.median(values)
                score_maxs[name] = max(values)

        # Calculate pass rate (runs where all assertions passed and no runtime error)
        passed_runs = sum(
            1
            for r in results
            if r.error is None and all(a.value is True for a in r.assertions.values())
        )

        return cls(
            runs=n,
            assertion_pass_rates=assertion_pass_rates,
            score_means=score_means,
            score_stdevs=score_stdevs,
            score_mins=score_mins,
            score_medians=score_medians,
            score_maxs=score_maxs,
            duration_mean=duration_mean,
            duration_stdev=duration_stdev,
            duration_min=duration_min,
            duration_median=duration_median,
            duration_max=duration_max,
            runtime_error_rate=runtime_errors / n,
            pass_rate=passed_runs / n,
        )


@dataclass
class ReportCase[InputsT, OutputT, MetadataT]:
    """Report for a single case.

    Attributes:
        name: Case name.
        inputs: The input data.
        expected_output: Expected output (if provided).
        metadata: Case metadata.
        run_results: Results from each run.
        stats: Aggregated statistics.

    """

    name: str
    inputs: InputsT
    expected_output: OutputT | None
    metadata: MetadataT | None
    run_results: list[RunResult[OutputT]] = field(
        default_factory=lambda: []  # noqa: PIE807
    )
    stats: ReportCaseStats = field(default_factory=lambda: ReportCaseStats(runs=0))

    def compute_stats(self) -> None:
        """Compute statistics from run results."""
        self.stats = ReportCaseStats.from_run_results(
            self.run_results  # pyright: ignore[reportArgumentType]
        )


@dataclass
class ModelConfig:
    """Configuration for a model used in evaluation.

    Attributes:
        model: Model name/identifier.
        temperature: Temperature setting (optional).
        max_tokens: Maximum tokens setting (optional).

    """

    model: str
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class EvaluationReport[InputsT, OutputT, MetadataT]:
    """Full evaluation report.

    Attributes:
        name: Report name.
        cases: Report for each case.
        repeats: Number of times each case was run.
        max_concurrency: Concurrency used during evaluation.
        models: Dictionary of model roles to model names used in evaluation.
        model_configs: Dictionary of model roles to full model configurations.
        additional_settings: Dictionary of additional settings to display in the report.

    """

    name: str
    cases: list[ReportCase[InputsT, OutputT, MetadataT]] = field(
        default_factory=lambda: []  # noqa: PIE807
    )
    repeats: int = 1
    max_concurrency: int = 10
    models: dict[str, str] = field(default_factory=lambda: {})  # noqa: PIE807
    model_configs: dict[str, ModelConfig] = field(default_factory=lambda: {})  # noqa: PIE807
    additional_settings: dict[str, Any] = field(default_factory=lambda: {})  # noqa: PIE807  # noqa: PIE807

    def print_summary(self) -> None:
        """Print a summary of the evaluation results."""
        print(f"\n{_BOLD}{'=' * 60}{_RESET}")
        print(f"{_BOLD}Evaluation Report: {_CYAN}{self.name}{_RESET}")
        print(f"Repeats: {self.repeats} | Concurrency: {self.max_concurrency}")
        if self.model_configs:
            print(f"{_BOLD}Model Configurations:{_RESET}")
            for role, config in self.model_configs.items():
                # Hide temperature for gpt-5 models (temperature not configurable)
                show_temp = config.temperature is not None and "gpt-5" not in config.model
                temp_str = f", temp={config.temperature}" if show_temp else ""
                # Hide max_tokens if 0 or None
                show_tokens = config.max_tokens is not None and config.max_tokens > 0
                tokens_str = f", max_tokens={config.max_tokens}" if show_tokens else ""
                print(f"  {role}: {_CYAN}{config.model}{_RESET}{temp_str}{tokens_str}")
        elif self.models:
            print(f"{_BOLD}Models:{_RESET}")
            for role, model in self.models.items():
                print(f"  {role}: {_CYAN}{model}{_RESET}")
        if self.additional_settings:
            print(f"{_BOLD}Additional Settings:{_RESET}")
            for key, value in self.additional_settings.items():
                display_key = key.replace("_", " ").title()
                print(f"  {display_key}: {_CYAN}{value}{_RESET}")
        print(f"{_BOLD}{'=' * 60}{_RESET}\n")

        for case in self.cases:
            stats = case.stats
            print(f"{_BOLD}Case: {_CYAN}{case.name}{_RESET}")
            pass_color = _GREEN if stats.pass_rate == 1.0 else _RED
            error_color = _RED if stats.runtime_error_rate > 0 else _GREEN
            pass_rate_str = f"{pass_color}{_fmt_pct(stats.pass_rate)}{_RESET}"
            error_rate_str = f"{error_color}{_fmt_pct(stats.runtime_error_rate)}{_RESET}"
            print(
                f"  Runs: {stats.runs} | Pass Rate: {pass_rate_str} | "
                f"Runtime Errors: {error_rate_str}"
            )
            print(
                f"  Duration: min={_CYAN}{_fmt_num(stats.duration_min, 3)}s{_RESET}, "
                f"median={_CYAN}{_fmt_num(stats.duration_median, 3)}s{_RESET}, "
                f"max={_CYAN}{_fmt_num(stats.duration_max, 3)}s{_RESET}"
            )

            if stats.assertion_pass_rates:
                print("  Assertions:")
                for name, rate in stats.assertion_pass_rates.items():
                    if rate == 1.0:
                        status = f"{_GREEN}✓{_RESET}"
                        rate_str = f"{_GREEN}{_fmt_pct(rate)}{_RESET}"
                    elif rate == 0.0:
                        status = f"{_RED}✗{_RESET}"
                        rate_str = f"{_RED}{_fmt_pct(rate)}{_RESET}"
                    else:
                        status = f"{_YELLOW}~{_RESET}"
                        rate_str = f"{_YELLOW}{_fmt_pct(rate)}{_RESET}"
                    print(f"    {status} {name}: {rate_str}")

            if stats.score_means:
                print("  Scores:")
                for name in stats.score_means:
                    min_val = stats.score_mins.get(name, 0.0)
                    median_val = stats.score_medians.get(name, 0.0)
                    max_val = stats.score_maxs.get(name, 0.0)
                    print(
                        f"    {name}: min={_CYAN}{_fmt_num(min_val)}{_RESET}, "
                        f"median={_CYAN}{_fmt_num(median_val)}{_RESET}, "
                        f"max={_CYAN}{_fmt_num(max_val)}{_RESET}"
                    )

            print()

        # Overall summary
        all_assertions: dict[str, list[float]] = {}
        all_scores: dict[str, list[float]] = {}

        for case in self.cases:
            for name, rate in case.stats.assertion_pass_rates.items():
                all_assertions.setdefault(name, []).append(rate)
            for name, mean in case.stats.score_means.items():
                all_scores.setdefault(name, []).append(mean)

        if all_assertions or all_scores:
            print(f"{_BOLD}{'=' * 60}{_RESET}")
            print(f"{_BOLD}OVERALL AVERAGES{_RESET}")
            print(f"{_BOLD}{'=' * 60}{_RESET}")

            if all_assertions:
                print("Assertions (avg pass rate):")
                for name, rates in all_assertions.items():
                    avg = statistics.mean(rates)
                    if avg == 1.0:
                        status = f"{_GREEN}✓{_RESET}"
                        avg_str = f"{_GREEN}{_fmt_pct(avg)}{_RESET}"
                    elif avg == 0.0:
                        status = f"{_RED}✗{_RESET}"
                        avg_str = f"{_RED}{_fmt_pct(avg)}{_RESET}"
                    else:
                        status = f"{_YELLOW}~{_RESET}"
                        avg_str = f"{_YELLOW}{_fmt_pct(avg)}{_RESET}"
                    print(f"  {status} {name}: {avg_str}")

            if all_scores:
                print("Scores (avg):")
                for name, means in all_scores.items():
                    avg = statistics.mean(means)
                    print(f"  {name}: {_CYAN}{_fmt_num(avg, 3)}{_RESET}")

            print()

    def report_id(self, generated_at: datetime) -> str:
        """Return a stable opaque identifier for structured report APIs."""
        timestamp = generated_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S-%f")
        slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-") or "eval"
        return f"eval-{slug}-{timestamp}"

    def render_markdown(self, *, generated_at: datetime) -> str:
        """Render the report as markdown without writing it as report storage."""
        lines: list[str] = []
        lines.append(f"# Evaluation Report: {self.name}\n")
        lines.append(f"**Generated:** {generated_at.isoformat()}\n")
        lines.append(f"**Repeats:** {self.repeats} | **Concurrency:** {self.max_concurrency}\n")

        # Model configurations section
        if self.model_configs:
            lines.append("\n## Model Configurations\n")
            # Check if we need temperature and max_tokens columns
            has_temp = any(
                c.temperature is not None and "gpt-5" not in c.model
                for c in self.model_configs.values()
            )
            has_tokens = any(
                c.max_tokens is not None and c.max_tokens > 0 for c in self.model_configs.values()
            )

            # Build header dynamically
            header = "| Role | Model |"
            separator = "|------|-------|"
            if has_temp:
                header += " Temperature |"
                separator += "-------------|"
            if has_tokens:
                header += " Max Tokens |"
                separator += "------------|"
            lines.append(header)
            lines.append(separator)

            for role, config in self.model_configs.items():
                row = f"| {role} | `{config.model}` |"
                if has_temp:
                    # Hide temperature for gpt-5 models
                    if config.temperature is not None and "gpt-5" not in config.model:
                        row += f" {_fmt_num(config.temperature)} |"
                    else:
                        row += " - |"
                if has_tokens:
                    # Hide max_tokens if 0 or None
                    if config.max_tokens is not None and config.max_tokens > 0:
                        row += f" {config.max_tokens} |"
                    else:
                        row += " - |"
                lines.append(row)
            lines.append("")
        elif self.models:
            lines.append("\n**Models:**\n")
            for role, model in self.models.items():
                lines.append(f"- {role}: `{model}`")
            lines.append("")

        # Additional settings section
        if self.additional_settings:
            lines.append("\n## Additional Settings\n")
            for key, value in self.additional_settings.items():
                display_key = key.replace("_", " ").title()
                lines.append(f"- **{display_key}:** `{value}`")
            lines.append("")

        # Summary section
        lines.append("\n## Summary\n")
        lines.append(
            "| Case | Runs | Pass Rate | Runtime Errors | Duration (min/med/max) | Assertions |"
        )
        lines.append(
            "|------|------|-----------|----------------|------------------------|------------|"
        )

        for case in self.cases:
            stats = case.stats
            duration_str = f"{_fmt_num(stats.duration_min, 2)}s / {_fmt_num(stats.duration_median, 2)}s / {_fmt_num(stats.duration_max, 2)}s"  # noqa: E501

            # Build assertion summary
            assertion_parts: list[str] = []
            for name, rate in stats.assertion_pass_rates.items():
                status = "✓" if rate == 1.0 else "✗" if rate == 0.0 else "~"
                assertion_parts.append(f"{status} {name}: {_fmt_pct(rate)}")
            assertions_str = ", ".join(assertion_parts) if assertion_parts else "-"

            lines.append(
                f"| {case.name} | {stats.runs} | {_fmt_pct(stats.pass_rate)} | "
                f"{_fmt_pct(stats.runtime_error_rate)} | {duration_str} | {assertions_str} |"
            )

        # Scores summary
        if any(case.stats.score_means for case in self.cases):
            lines.append("\n### Scores\n")
            lines.append("| Case | Score | Min | Median | Max |")
            lines.append("|------|-------|-----|--------|-----|")
            for case in self.cases:
                for name in case.stats.score_means:
                    min_val = case.stats.score_mins.get(name, 0.0)
                    median_val = case.stats.score_medians.get(name, 0.0)
                    max_val = case.stats.score_maxs.get(name, 0.0)
                    lines.append(
                        f"| {case.name} | {name} | {_fmt_num(min_val)} | {_fmt_num(median_val)} | {_fmt_num(max_val)} |"  # noqa: E501
                    )

        # Overall averages
        all_assertions: dict[str, list[float]] = {}
        all_scores: dict[str, list[float]] = {}
        for case in self.cases:
            for name, rate in case.stats.assertion_pass_rates.items():
                all_assertions.setdefault(name, []).append(rate)
            for name, mean in case.stats.score_means.items():
                all_scores.setdefault(name, []).append(mean)

        if all_assertions or all_scores:
            lines.append("\n## Overall Averages\n")
            if all_assertions:
                lines.append("**Assertions:**\n")
                for name, rates in all_assertions.items():
                    avg = statistics.mean(rates)
                    status = "✓" if avg == 1.0 else "✗" if avg == 0.0 else "~"
                    lines.append(f"- {status} {name}: {_fmt_pct(avg)}")
                lines.append("")

            if all_scores:
                lines.append("**Scores:**\n")
                for name, means in all_scores.items():
                    avg = statistics.mean(means)
                    lines.append(f"- {name}: {_fmt_num(avg, 3)}")
                lines.append("")

        # Failed runs section
        lines.append("\n## Failed Runs\n")

        has_failures = False
        for case in self.cases:
            failed_runs: list[tuple[int, RunResult[OutputT]]] = []
            for i, run in enumerate(case.run_results):
                # Check if any assertion failed
                any_failed = (
                    any(a.value is False for a in run.assertions.values()) or run.error is not None
                )
                if any_failed:
                    failed_runs.append((i, run))

            if failed_runs:
                has_failures = True
                lines.append(f"### Case: {case.name}\n")

                # Show input fields separately
                lines.extend(self._format_object_fields(case.inputs, "Input"))

                for run_idx, run in failed_runs:
                    lines.append(f"#### Run {run_idx + 1}\n")

                    if run.error:
                        lines.append(f"**Error:** {run.error}\n")
                    else:
                        # Show output fields separately (excluding system_prompt)
                        lines.extend(
                            self._format_object_fields(
                                run.output, "Output", exclude=_EXCLUDED_OUTPUT_FIELDS
                            )
                        )

                        # Show assertion details
                        lines.append("**Assertions:**\n")
                        for name, result in run.assertions.items():
                            status = "✓ PASS" if result.value else "✗ FAIL"
                            lines.append(f"- **{name}:** {status}")
                            if result.reason:
                                lines.append(f"  - Reason: {result.reason}")
                        lines.append("")

                    lines.append(f"**Duration:** {_fmt_num(run.duration, 3)}s\n")
                    if run.otel_trace_id is not None:
                        lines.append(f"**OTel Trace ID:** `{run.otel_trace_id}`\n")
                    if run.otel_span_id is not None:
                        lines.append(f"**OTel Span ID:** `{run.otel_span_id}`\n")
                    lines.append("---\n")

        if not has_failures:
            lines.append("*No failed runs.*\n")

        return "\n".join(lines)

    def write_report(self, output_dir: str | Path = "reports", *, announce: bool = True) -> Path:
        """Write a markdown report file with summary and failed run details.

        Args:
            output_dir: Directory to write the report to.
            announce: Whether to print the written report path.

        Returns:
            Path to the written report file.

        """
        generated_at = datetime.now(UTC)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        report_file = output_path / f"{self.report_id(generated_at)}.md"
        report_file.write_text(self.render_markdown(generated_at=generated_at), encoding="utf-8")
        if announce:
            print(f"{_GREEN}Report written to: {report_file}{_RESET}")
        return report_file

    def _format_object_fields(
        self, obj: Any, section_name: str, exclude: set[str] | None = None
    ) -> list[str]:
        """Format an object's fields as separate markdown sections.

        Args:
            obj: The object to format.
            section_name: Name prefix for the section (e.g., "Input", "Output").
            exclude: Set of field names to exclude from output.

        Returns:
            List of markdown lines.

        """
        lines: list[str] = []
        exclude = exclude or set()

        if obj is None:
            lines.append(f"**{section_name}:** None\n")
            return lines

        def append_field(field_name: str, value: Any) -> None:
            display_name = field_name.replace("_", " ").title()
            if isinstance(value, str):
                is_multiline_or_long = "\n" in value or len(value) > _INLINE_VALUE_MAX_LENGTH
                if is_multiline_or_long:
                    lines.append(f"**{display_name}:**\n")
                    lines.append("```")
                    lines.append(value)
                    lines.append("```\n")
                    return
            lines.append(f"**{display_name}:** `{value}`\n")

        if hasattr(obj, "__dataclass_fields__"):
            field_names = cast(Mapping[str, Any], obj.__dataclass_fields__)
            for field_name in field_names:
                if field_name not in exclude:
                    append_field(field_name, getattr(obj, field_name))
        elif isinstance(obj, Mapping):
            obj_mapping = cast(Mapping[str, Any], obj)
            for field_name, value in obj_mapping.items():
                if str(field_name) not in exclude:
                    append_field(str(field_name), value)
        else:
            lines.append(f"**{section_name}:**\n")
            lines.append("```")
            lines.append(str(obj))
            lines.append("```\n")

        return lines
