"""Read-only CLI for inspecting structured eval reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.rag_data import create_session_factory
from app.evals.storage import eval_report_session, get_eval_report, list_eval_reports
from app.evals.test_db import create_test_db_engine
from app.models import EvalCaseResult, EvalCaseRunResult, EvalRunRecord

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@dataclass(frozen=True)
class CliContext:
    json_output: bool
    db_url: str | None


@asynccontextmanager
async def _open_session(db_url: str | None) -> AsyncGenerator[AsyncSession]:
    if db_url is None:
        async with eval_report_session() as session:
            yield session
        return

    engine = create_test_db_engine(db_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _print_json(value: Any) -> None:
    print(json.dumps(value, default=_json_default, ensure_ascii=False, indent=2))


def _result_value(result: dict[str, Any]) -> Any:
    return result.get("value")


def _result_reason(result: dict[str, Any]) -> str | None:
    reason = result.get("reason")
    return reason if isinstance(reason, str) and reason.strip() else None


def _result_failed(result: dict[str, Any]) -> bool:
    value = _result_value(result)
    if isinstance(value, bool):
        return not value
    if isinstance(value, dict):
        value_dict = cast(dict[str, object], value)
        nested_value = value_dict.get("value")
        if isinstance(nested_value, bool):
            return not nested_value
    return False


def _run_failed(run: EvalCaseRunResult) -> bool:
    return run.error is not None or any(
        _result_failed(result) for result in run.assertions.values()
    )


def _case_failed(case: EvalCaseResult) -> bool:
    return any(_run_failed(run) for run in case.runs)


def _pass_rate(report: EvalRunRecord) -> float | None:
    total_runs = sum(len(case.runs) for case in report.cases)
    if total_runs == 0:
        return None
    failed_runs = sum(1 for case in report.cases for run in case.runs if _run_failed(run))
    return (total_runs - failed_runs) / total_runs


def _response_text(output: dict[str, Any] | None) -> str | None:
    if output is None:
        return None
    for key in ("chatbot_response", "response"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key, value in output.items():
        if key.endswith("_response") and isinstance(value, str) and value.strip():
            return value
    return None


def _run_to_dict(run: EvalCaseRunResult) -> dict[str, Any]:
    return {
        "run_index": run.run_index,
        "failed": _run_failed(run),
        "duration": run.duration,
        "error": run.error,
        "otel_trace_id": run.otel_trace_id,
        "otel_span_id": run.otel_span_id,
        "output": run.output,
        "response": _response_text(run.output),
        "assertions": run.assertions,
        "scores": run.scores,
        "labels": run.labels,
    }


def _case_to_dict(case: EvalCaseResult, *, include_runs: bool = True) -> dict[str, Any]:
    return {
        "name": case.name,
        "failed": _case_failed(case),
        "inputs": case.inputs,
        "expected_output": case.expected_output,
        "metadata": case.metadata_json,
        "stats": case.stats,
        "runs": [_run_to_dict(run) for run in case.runs] if include_runs else [],
    }


def _report_summary_to_dict(report: EvalRunRecord) -> dict[str, Any]:
    case_count = len(report.cases)
    run_count = sum(len(case.runs) for case in report.cases)
    failed_case_count = sum(1 for case in report.cases if _case_failed(case))
    failed_run_count = sum(1 for case in report.cases for run in case.runs if _run_failed(run))
    return {
        "report_id": report.report_id,
        "title": report.name,
        "suite": report.suite,
        "status": report.status,
        "generated_at": report.generated_at,
        "repeats": report.repeats,
        "max_concurrency": report.max_concurrency,
        "pass_threshold": report.pass_threshold,
        "pass_rate": _pass_rate(report),
        "case_count": case_count,
        "run_count": run_count,
        "failed_case_count": failed_case_count,
        "failed_run_count": failed_run_count,
        "log_id": report.log_id,
    }


def _report_detail_to_dict(report: EvalRunRecord) -> dict[str, Any]:
    return {
        **_report_summary_to_dict(report),
        "config": report.config,
        "model_configs": report.model_configs,
        "additional_settings": report.additional_settings,
        "cases": [_case_to_dict(case) for case in report.cases],
    }


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _print_report_table(reports: list[EvalRunRecord]) -> None:
    if not reports:
        print("No eval reports found.")
        return

    rows = [_report_summary_to_dict(report) for report in reports]
    header = "generated_at           suite    status     pass    failed  report_id"
    print(header)
    print("-" * len(header))
    for row in rows:
        generated_at = str(row["generated_at"])[:19]
        suite = str(row["suite"])[:7]
        status = str(row["status"])[:9]
        pass_rate = _format_percent(row["pass_rate"])
        failed = f"{row['failed_case_count']}/{row['case_count']}"
        print(
            f"{generated_at:<22} {suite:<7} {status:<9} {pass_rate:<7} "
            f"{failed:<7} {row['report_id']}"
        )


def _print_report_detail(report: EvalRunRecord) -> None:
    summary = _report_summary_to_dict(report)
    print(f"Report: {summary['report_id']}")
    print(f"Title: {summary['title']}")
    print(f"Suite: {summary['suite']}")
    print(f"Status: {summary['status']}")
    print(f"Generated: {summary['generated_at']}")
    print(f"Pass rate: {_format_percent(summary['pass_rate'])}")
    print(f"Cases: {summary['case_count']} ({summary['failed_case_count']} failed)")
    print(f"Runs: {summary['run_count']} ({summary['failed_run_count']} failed)")
    if summary["log_id"]:
        print(f"Log: {summary['log_id']}")
    print()
    print("Cases:")
    for case in report.cases:
        marker = "FAIL" if _case_failed(case) else "PASS"
        print(f"  [{marker}] {case.name} ({len(case.runs)} run(s))")


def _print_failures(report: EvalRunRecord) -> None:
    failed_cases = [case for case in report.cases if _case_failed(case)]
    if not failed_cases:
        print(f"No failed cases in {report.report_id}.")
        return

    print(f"Failures for {report.report_id}:")
    for case in failed_cases:
        print(f"\nCase: {case.name}")
        for run in case.runs:
            if not _run_failed(run):
                continue
            print(f"  Run #{run.run_index} ({run.duration:.2f}s)")
            if run.error:
                print("    Error:")
                for line in run.error.splitlines():
                    print(f"      {line}")
            for name, result in run.assertions.items():
                if not _result_failed(result):
                    continue
                print(f"    Assertion failed: {name}")
                reason = _result_reason(result)
                if reason:
                    print(f"      {reason}")
            if run.otel_trace_id:
                span_suffix = f"?span={run.otel_span_id}" if run.otel_span_id else ""
                print(f"    Trace: {run.otel_trace_id}{span_suffix}")
            response = _response_text(run.output)
            if response:
                print("    Response:")
                for line in response.splitlines()[:12]:
                    print(f"      {line}")


def _print_case(case: EvalCaseResult) -> None:
    print(f"Case: {case.name}")
    print(f"Status: {'FAIL' if _case_failed(case) else 'PASS'}")
    print("Inputs:")
    print(json.dumps(case.inputs, ensure_ascii=False, indent=2, default=_json_default))
    if case.expected_output is not None:
        print("Expected:")
        print(json.dumps(case.expected_output, ensure_ascii=False, indent=2, default=_json_default))
    print("Runs:")
    for run in case.runs:
        marker = "FAIL" if _run_failed(run) else "PASS"
        print(f"  Run #{run.run_index}: {marker} ({run.duration:.2f}s)")
        if run.error:
            print("    Error:")
            for line in run.error.splitlines():
                print(f"      {line}")
        if run.assertions:
            print("    Assertions:")
            for name, result in run.assertions.items():
                marker = "FAIL" if _result_failed(result) else "PASS"
                reason = _result_reason(result)
                print(f"      [{marker}] {name}")
                if reason:
                    print(f"        {reason}")
        response = _response_text(run.output)
        if response:
            print("    Response:")
            for line in response.splitlines():
                print(f"      {line}")
        if run.otel_trace_id:
            span_suffix = f"?span={run.otel_span_id}" if run.otel_span_id else ""
            print(f"    Trace: {run.otel_trace_id}{span_suffix}")


async def _load_report_or_exit(ctx: CliContext, report_id: str) -> EvalRunRecord:
    async with _open_session(ctx.db_url) as session:
        report = await get_eval_report(session, report_id)
    if report is None:
        print(f"Eval report not found: {report_id}", file=sys.stderr)
        raise SystemExit(1)
    return report


async def _cmd_list(args: argparse.Namespace, ctx: CliContext) -> None:
    async with _open_session(ctx.db_url) as session:
        reports = await list_eval_reports(session, limit=args.limit, search=args.search)
    if ctx.json_output:
        _print_json([_report_summary_to_dict(report) for report in reports])
        return
    _print_report_table(reports)


async def _cmd_show(args: argparse.Namespace, ctx: CliContext) -> None:
    report = await _load_report_or_exit(ctx, args.report_id)
    if ctx.json_output:
        _print_json(_report_detail_to_dict(report))
        return
    _print_report_detail(report)


async def _cmd_failures(args: argparse.Namespace, ctx: CliContext) -> None:
    report = await _load_report_or_exit(ctx, args.report_id)
    if ctx.json_output:
        _print_json(
            {
                "report": _report_summary_to_dict(report),
                "cases": [_case_to_dict(case) for case in report.cases if _case_failed(case)],
            }
        )
        return
    _print_failures(report)


async def _cmd_case(args: argparse.Namespace, ctx: CliContext) -> None:
    report = await _load_report_or_exit(ctx, args.report_id)
    case = next((item for item in report.cases if item.name == args.case_id), None)
    if case is None:
        print(f"Eval case not found in {report.report_id}: {args.case_id}", file=sys.stderr)
        raise SystemExit(1)
    if ctx.json_output:
        _print_json({"report": _report_summary_to_dict(report), "case": _case_to_dict(case)})
        return
    _print_case(case)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.evals.inspect",
        description="Inspect structured eval reports from the guarded eval/test database.",
    )
    parser.add_argument("--json", action="store_true", help="print structured JSON to stdout")
    parser.add_argument(
        "--db-url", help="database URL override; defaults to guarded migrated eval/test database"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list recent eval reports")
    list_parser.add_argument("--limit", type=int, default=20, help="maximum reports to show")
    list_parser.add_argument("--search", help="filter reports by title or report id")
    list_parser.set_defaults(handler=_cmd_list)

    show_parser = subparsers.add_parser("show", help="show report summary and cases")
    show_parser.add_argument("report_id", help="eval report id")
    show_parser.set_defaults(handler=_cmd_show)

    failures_parser = subparsers.add_parser("failures", help="show failed cases/runs")
    failures_parser.add_argument("report_id", help="eval report id")
    failures_parser.set_defaults(handler=_cmd_failures)

    case_parser = subparsers.add_parser("case", help="show one case and its runs")
    case_parser.add_argument("report_id", help="eval report id")
    case_parser.add_argument("case_id", help="case id/name")
    case_parser.set_defaults(handler=_cmd_case)

    return parser


async def _main_async(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "list" and args.limit < 1:
        parser.error("--limit must be at least 1")
    ctx = CliContext(json_output=args.json, db_url=args.db_url)
    await args.handler(args, ctx)


def main(argv: list[str] | None = None) -> None:
    try:
        asyncio.run(_main_async(argv))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
