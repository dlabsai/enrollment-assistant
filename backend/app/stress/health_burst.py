"""Monotonic, token-free FastAPI health-endpoint burst tester."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

_DEFAULT_CONCURRENCY = (1, 25, 50, 100, 250)
_DEFAULT_PATH = "/api/utils/health-check/"
_OK_STATUS = 200
_MIN_PROCESS_CPU_WINDOW_SECONDS = 0.05
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class CliError(Exception):
    """Expected command failure with a stable exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ClockInvariantError(RuntimeError):
    """Raised if a supposedly monotonic duration goes backwards."""


@dataclass(frozen=True)
class RequestResult:
    elapsed_ms: float
    status_code: int | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.status_code == _OK_STATUS


@dataclass(frozen=True)
class ProcessSnapshot:
    monotonic_ns: int
    cpu_seconds: float
    rss_bytes: int
    pids: tuple[int, ...]


@dataclass(frozen=True)
class ProcessRoundMetrics:
    cpu_percent: float | None
    peak_rss_bytes: int
    minimum_processes: int
    maximum_processes: int
    process_set_changed: bool


@dataclass(frozen=True)
class RoundResult:
    index: int
    concurrency: int
    wall_ms: float
    client_cpu_percent: float
    requests: tuple[RequestResult, ...]
    process_metrics: ProcessRoundMetrics | None


@dataclass(frozen=True)
class LevelSummary:
    concurrency: int
    rounds: int
    requests: int
    errors: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    maximum_ms: float
    average_round_wall_ms: float
    requests_per_second: float
    maximum_client_cpu_percent: float
    maximum_cpu_percent: float | None
    peak_rss_bytes: int | None
    process_set_changed: bool


@dataclass(frozen=True)
class RunConfig:
    base_url: str
    path: str
    concurrency: tuple[int, ...]
    rounds: int
    warmup_rounds: int
    request_timeout_seconds: float
    settle_seconds: float
    round_pause_seconds: float
    process_matches: tuple[str, ...]
    process_sample_interval_seconds: float

    @property
    def target_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.path.lstrip('/')}"


class ProcessSampler:
    """Sample matching Linux processes using monotonic time and procfs."""

    def __init__(self, matches: Sequence[str], sample_interval_seconds: float) -> None:
        self._matches = tuple(matches)
        self._sample_interval_seconds = sample_interval_seconds
        self._excluded_pids = _ancestor_pids()
        self._samples: list[ProcessSnapshot] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._matches:
            return
        self.capture()
        self._thread = threading.Thread(
            target=self._run, name="health-burst-process-sampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def capture(self) -> ProcessSnapshot | None:
        if not self._matches:
            return None
        snapshot = _capture_matching_processes(self._matches, self._excluded_pids)
        with self._lock:
            self._samples.append(snapshot)
        return snapshot

    def metrics_between(
        self, *, started_ns: int, ended_ns: int, before: ProcessSnapshot, after: ProcessSnapshot
    ) -> ProcessRoundMetrics:
        with self._lock:
            samples = [
                sample for sample in self._samples if started_ns <= sample.monotonic_ns <= ended_ns
            ]
        samples = [before, *samples, after]
        process_counts = [len(sample.pids) for sample in samples]
        peak_rss_bytes = max(sample.rss_bytes for sample in samples)
        process_set_changed = before.pids != after.pids or any(
            sample.pids != before.pids for sample in samples
        )
        wall_seconds = _elapsed_ms(started_ns, ended_ns) / 1000
        cpu_delta = after.cpu_seconds - before.cpu_seconds
        cpu_percent = None
        if (
            not process_set_changed
            and cpu_delta >= 0
            and wall_seconds >= _MIN_PROCESS_CPU_WINDOW_SECONDS
        ):
            cpu_percent = cpu_delta / wall_seconds * 100
        return ProcessRoundMetrics(
            cpu_percent=cpu_percent,
            peak_rss_bytes=peak_rss_bytes,
            minimum_processes=min(process_counts),
            maximum_processes=max(process_counts),
            process_set_changed=process_set_changed,
        )

    def maximum_observed_processes(self) -> int:
        with self._lock:
            return max((len(sample.pids) for sample in self._samples), default=0)

    def _run(self) -> None:
        while not self._stop.wait(self._sample_interval_seconds):
            self.capture()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.stress.health_burst",
        description=(
            "Send synchronized, token-free health-check bursts using monotonic timing. "
            "Remote targets require --allow-remote."
        ),
    )
    parser.add_argument("--version", action="version", version="app.stress.health_burst 0.1")
    parser.add_argument(
        "--base-url", required=True, help="backend origin, for example http://localhost:8000"
    )
    parser.add_argument(
        "--path", default=_DEFAULT_PATH, help=f"health endpoint path; default: {_DEFAULT_PATH}"
    )
    parser.add_argument(
        "--concurrency",
        action="append",
        type=_positive_int,
        help=(
            "simultaneous requests; repeat for multiple levels. "
            "Defaults to 1, 25, 50, 100, and 250."
        ),
    )
    parser.add_argument(
        "--rounds", type=_positive_int, default=5, help="timed bursts per level; default: 5"
    )
    parser.add_argument(
        "--warmup-rounds",
        type=_non_negative_int,
        default=1,
        help="untimed connection-warming bursts per level; default: 1",
    )
    parser.add_argument(
        "--request-timeout",
        type=_positive_float,
        default=10.0,
        metavar="SECONDS",
        help="timeout for each request; default: 10",
    )
    parser.add_argument(
        "--settle-seconds",
        type=_non_negative_float,
        default=0.5,
        help="pause after warmup; default: 0.5",
    )
    parser.add_argument(
        "--round-pause-seconds",
        type=_non_negative_float,
        default=0.5,
        help="pause between timed bursts; default: 0.5",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow a non-localhost target; required as an explicit safety acknowledgement",
    )
    parser.add_argument(
        "--process-match",
        action="append",
        default=[],
        help=(
            "Linux /proc command-line substring to monitor; repeat to match alternatives. "
            "Example: --process-match 'app.static_app:app'."
        ),
    )
    parser.add_argument(
        "--process-sample-ms",
        type=_positive_float,
        default=50.0,
        help="process RSS sampling interval in milliseconds; default: 50",
    )
    parser.add_argument(
        "--json", action="store_true", help="write stable structured JSON instead of human output"
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


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a finite number greater than zero")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a finite number zero or greater")
    return parsed


def _normalize_base_url(value: str, *, allow_remote: bool) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise CliError("--base-url must be an absolute http:// or https:// URL", exit_code=2)
    if parsed.query or parsed.fragment:
        raise CliError("--base-url must not contain a query string or fragment", exit_code=2)
    if not allow_remote and parsed.hostname.lower() not in _LOCAL_HOSTS:
        raise CliError(
            f"refusing non-local target without --allow-remote: {parsed.hostname}", exit_code=2
        )
    return normalized


def _normalize_concurrency(values: Sequence[int] | None) -> tuple[int, ...]:
    source = values or _DEFAULT_CONCURRENCY
    return tuple(dict.fromkeys(source))


def _elapsed_ms(started_ns: int, ended_ns: int) -> float:
    elapsed_ns = ended_ns - started_ns
    if elapsed_ns < 0:
        raise ClockInvariantError(
            "monotonic clock moved backwards; refusing to report a negative duration"
        )
    return elapsed_ns / 1_000_000


async def _request_after_gate(
    client: httpx.AsyncClient, target_url: str, ready: asyncio.Event, start: asyncio.Event
) -> RequestResult:
    ready.set()
    await start.wait()
    started_ns = time.perf_counter_ns()
    try:
        response = await client.get(target_url)
        ended_ns = time.perf_counter_ns()
        elapsed_ms = _elapsed_ms(started_ns, ended_ns)
        if response.status_code != _OK_STATUS:
            return RequestResult(
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                error=f"unexpected HTTP status {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError:
            return RequestResult(
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                error="response was not valid JSON",
            )
        if payload is not True:
            return RequestResult(
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                error="health response body was not JSON true",
            )
        return RequestResult(elapsed_ms=elapsed_ms, status_code=_OK_STATUS, error=None)
    except httpx.HTTPError as exc:
        ended_ns = time.perf_counter_ns()
        return RequestResult(
            elapsed_ms=_elapsed_ms(started_ns, ended_ns),
            status_code=None,
            error=f"{type(exc).__name__}: {exc}",
        )


async def _run_burst(
    *,
    client: httpx.AsyncClient,
    target_url: str,
    concurrency: int,
    index: int,
    sampler: ProcessSampler,
) -> RoundResult:
    start = asyncio.Event()
    ready = [asyncio.Event() for _ in range(concurrency)]
    tasks = [
        asyncio.create_task(_request_after_gate(client, target_url, event, start))
        for event in ready
    ]
    await asyncio.gather(*(event.wait() for event in ready))

    before = sampler.capture()
    client_cpu_started_ns = time.process_time_ns()
    started_ns = time.perf_counter_ns()
    start.set()
    requests = tuple(await asyncio.gather(*tasks))
    ended_ns = time.perf_counter_ns()
    client_cpu_ended_ns = time.process_time_ns()
    after = sampler.capture()

    process_metrics = None
    if before is not None and after is not None:
        process_metrics = sampler.metrics_between(
            started_ns=started_ns, ended_ns=ended_ns, before=before, after=after
        )
    wall_ms = _elapsed_ms(started_ns, ended_ns)
    client_cpu_ms = _elapsed_ms(client_cpu_started_ns, client_cpu_ended_ns)
    return RoundResult(
        index=index,
        concurrency=concurrency,
        wall_ms=wall_ms,
        client_cpu_percent=client_cpu_ms / wall_ms * 100,
        requests=requests,
        process_metrics=process_metrics,
    )


async def _warm_up(
    *, client: httpx.AsyncClient, target_url: str, concurrency: int, rounds: int
) -> None:
    sampler = ProcessSampler((), 1)
    for index in range(1, rounds + 1):
        result = await _run_burst(
            client=client,
            target_url=target_url,
            concurrency=concurrency,
            index=index,
            sampler=sampler,
        )
        errors = [request.error for request in result.requests if not request.succeeded]
        if errors:
            raise CliError(f"warmup failed at concurrency {concurrency}: {errors[0]}")


async def run_health_burst(
    config: RunConfig, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[RoundResult, ...]:
    sampler = ProcessSampler(config.process_matches, config.process_sample_interval_seconds)
    sampler.start()
    limits = httpx.Limits(
        max_connections=max(config.concurrency), max_keepalive_connections=max(config.concurrency)
    )
    timeout = httpx.Timeout(config.request_timeout_seconds)
    results: list[RoundResult] = []
    try:
        async with httpx.AsyncClient(limits=limits, timeout=timeout, transport=transport) as client:
            for concurrency in config.concurrency:
                await _warm_up(
                    client=client,
                    target_url=config.target_url,
                    concurrency=concurrency,
                    rounds=config.warmup_rounds,
                )
                if config.settle_seconds:
                    await asyncio.sleep(config.settle_seconds)
                for round_index in range(1, config.rounds + 1):
                    results.append(
                        await _run_burst(
                            client=client,
                            target_url=config.target_url,
                            concurrency=concurrency,
                            index=round_index,
                            sampler=sampler,
                        )
                    )
                    if config.round_pause_seconds and round_index != config.rounds:
                        await asyncio.sleep(config.round_pause_seconds)
    finally:
        sampler.stop()

    if config.process_matches and sampler.maximum_observed_processes() == 0:
        raise CliError("no Linux processes matched --process-match; HTTP results were not reported")
    return tuple(results)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile for empty values")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def summarize_level(concurrency: int, rounds: Sequence[RoundResult]) -> LevelSummary:
    if not rounds:
        raise ValueError("cannot summarize an empty level")
    requests = [request for round_result in rounds for request in round_result.requests]
    elapsed = [request.elapsed_ms for request in requests]
    total_wall_seconds = sum(round_result.wall_ms for round_result in rounds) / 1000
    process_metrics = [
        round_result.process_metrics
        for round_result in rounds
        if round_result.process_metrics is not None
    ]
    cpu_values = [
        metrics.cpu_percent for metrics in process_metrics if metrics.cpu_percent is not None
    ]
    return LevelSummary(
        concurrency=concurrency,
        rounds=len(rounds),
        requests=len(requests),
        errors=sum(not request.succeeded for request in requests),
        p50_ms=_percentile(elapsed, 0.5),
        p95_ms=_percentile(elapsed, 0.95),
        p99_ms=_percentile(elapsed, 0.99),
        maximum_ms=max(elapsed),
        average_round_wall_ms=statistics.mean(round_result.wall_ms for round_result in rounds),
        requests_per_second=len(requests) / total_wall_seconds,
        maximum_client_cpu_percent=max(round_result.client_cpu_percent for round_result in rounds),
        maximum_cpu_percent=max(cpu_values) if cpu_values else None,
        peak_rss_bytes=(
            max(metrics.peak_rss_bytes for metrics in process_metrics) if process_metrics else None
        ),
        process_set_changed=any(metrics.process_set_changed for metrics in process_metrics),
    )


def summarize_run(
    concurrency_levels: Sequence[int], rounds: Sequence[RoundResult]
) -> tuple[LevelSummary, ...]:
    return tuple(
        summarize_level(
            concurrency,
            [round_result for round_result in rounds if round_result.concurrency == concurrency],
        )
        for concurrency in concurrency_levels
    )


def _request_payload(result: RequestResult) -> dict[str, Any]:
    return {
        "elapsed_ms": result.elapsed_ms,
        "status_code": result.status_code,
        "error": result.error,
    }


def _process_metrics_payload(metrics: ProcessRoundMetrics | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {
        "cpu_percent": metrics.cpu_percent,
        "peak_rss_bytes": metrics.peak_rss_bytes,
        "minimum_processes": metrics.minimum_processes,
        "maximum_processes": metrics.maximum_processes,
        "process_set_changed": metrics.process_set_changed,
    }


def _round_payload(result: RoundResult) -> dict[str, Any]:
    return {
        "index": result.index,
        "concurrency": result.concurrency,
        "wall_ms": result.wall_ms,
        "client_cpu_percent": result.client_cpu_percent,
        "errors": sum(not request.succeeded for request in result.requests),
        "process_metrics": _process_metrics_payload(result.process_metrics),
        "requests": [_request_payload(request) for request in result.requests],
    }


def _summary_payload(summary: LevelSummary) -> dict[str, Any]:
    return {
        "concurrency": summary.concurrency,
        "rounds": summary.rounds,
        "requests": summary.requests,
        "errors": summary.errors,
        "p50_ms": summary.p50_ms,
        "p95_ms": summary.p95_ms,
        "p99_ms": summary.p99_ms,
        "maximum_ms": summary.maximum_ms,
        "average_round_wall_ms": summary.average_round_wall_ms,
        "requests_per_second": summary.requests_per_second,
        "maximum_client_cpu_percent": summary.maximum_client_cpu_percent,
        "maximum_cpu_percent": summary.maximum_cpu_percent,
        "peak_rss_bytes": summary.peak_rss_bytes,
        "process_set_changed": summary.process_set_changed,
    }


def _print_human(config: RunConfig, summaries: Sequence[LevelSummary]) -> None:
    print("FastAPI health microburst")
    print(f"Target: {config.target_url}")
    print("Clock: time.perf_counter_ns (monotonic; wall time is not used for durations)")
    if config.process_matches:
        print(f"Process matches: {', '.join(config.process_matches)}")
    print()
    for summary in summaries:
        process_suffix = ""
        if summary.maximum_cpu_percent is not None and summary.peak_rss_bytes is not None:
            process_suffix = (
                f" cpu_max={summary.maximum_cpu_percent:.1f}% "
                f"rss_peak={summary.peak_rss_bytes / (1024 * 1024):.1f}MiB"
            )
        if summary.process_set_changed:
            process_suffix += " process_set_changed=yes"
        print(
            f"c={summary.concurrency:<3} n={summary.requests:<4} errors={summary.errors:<3} "
            f"p50={summary.p50_ms:7.2f}ms p95={summary.p95_ms:7.2f}ms "
            f"p99={summary.p99_ms:7.2f}ms max={summary.maximum_ms:7.2f}ms "
            f"throughput={summary.requests_per_second:8.1f}/s "
            f"client_cpu_max={summary.maximum_client_cpu_percent:5.1f}%{process_suffix}"
        )


def _capture_matching_processes(
    matches: Sequence[str], excluded_pids: frozenset[int]
) -> ProcessSnapshot:
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    cpu_seconds = 0.0
    rss_bytes = 0
    pids: list[int] = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        pid = int(path.name)
        if pid in excluded_pids:
            continue
        try:
            command = (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if not command or not any(match in command for match in matches):
                continue
            stat = (path / "stat").read_text()
            fields = stat[stat.rfind(")") + 2 :].split()
            user_ticks = int(fields[11])
            system_ticks = int(fields[12])
            statm = (path / "statm").read_text().split()
            resident_pages = int(statm[1])
        except FileNotFoundError, IndexError, PermissionError, ProcessLookupError, ValueError:
            continue
        pids.append(pid)
        cpu_seconds += (user_ticks + system_ticks) / ticks_per_second
        rss_bytes += resident_pages * page_size
    return ProcessSnapshot(
        monotonic_ns=time.perf_counter_ns(),
        cpu_seconds=cpu_seconds,
        rss_bytes=rss_bytes,
        pids=tuple(sorted(pids)),
    )


def _ancestor_pids() -> frozenset[int]:
    ancestors: set[int] = set()
    pid = os.getpid()
    while pid > 0 and pid not in ancestors:
        ancestors.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            fields = stat[stat.rfind(")") + 2 :].split()
            pid = int(fields[1])
        except FileNotFoundError, IndexError, PermissionError, ValueError:
            break
    return frozenset(ancestors)


async def _main_async(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        allow_remote = cast(bool, args.allow_remote)
        config = RunConfig(
            base_url=_normalize_base_url(cast(str, args.base_url), allow_remote=allow_remote),
            path=cast(str, args.path),
            concurrency=_normalize_concurrency(cast(Sequence[int] | None, args.concurrency)),
            rounds=cast(int, args.rounds),
            warmup_rounds=cast(int, args.warmup_rounds),
            request_timeout_seconds=cast(float, args.request_timeout),
            settle_seconds=cast(float, args.settle_seconds),
            round_pause_seconds=cast(float, args.round_pause_seconds),
            process_matches=tuple(cast(list[str], args.process_match)),
            process_sample_interval_seconds=cast(float, args.process_sample_ms) / 1000,
        )
        run_started_at_utc = datetime.now(tz=UTC).isoformat()
        rounds = await run_health_burst(config)
        summaries = summarize_run(config.concurrency, rounds)
    except (CliError, ClockInvariantError) as exc:
        exit_code = exc.exit_code if isinstance(exc, CliError) else 1
        print(f"error: {exc}", file=sys.stderr)
        return exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if cast(bool, args.json):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "started_at_utc": run_started_at_utc,
                    "clock": "time.perf_counter_ns",
                    "target_url": config.target_url,
                    "config": {
                        "concurrency": list(config.concurrency),
                        "rounds": config.rounds,
                        "warmup_rounds": config.warmup_rounds,
                        "request_timeout_seconds": config.request_timeout_seconds,
                        "settle_seconds": config.settle_seconds,
                        "round_pause_seconds": config.round_pause_seconds,
                        "process_matches": list(config.process_matches),
                        "process_sample_interval_seconds": (config.process_sample_interval_seconds),
                    },
                    "success": all(summary.errors == 0 for summary in summaries),
                    "summaries": [_summary_payload(summary) for summary in summaries],
                    "rounds": [_round_payload(round_result) for round_result in rounds],
                },
                indent=2,
            )
        )
    else:
        _print_human(config, summaries)
    return 0 if all(summary.errors == 0 for summary in summaries) else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
