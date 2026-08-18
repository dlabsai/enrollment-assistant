"""Strictly read-only PostgreSQL vector-search concurrency harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, LiteralString, cast

import psycopg
from psycopg import sql

_QUERY = """
SELECT c.id, c.sequence_number, d.type, d.id_
FROM document_content_chunk AS c
JOIN document AS d ON c.document_id = d.id
WHERE d.type IN (
  'website_page',
  'website_program',
  'catalog_page',
  'catalog_program',
  'catalog_course',
  'training_material'
)
  AND NOT EXISTS (
    SELECT 1 FROM rag_document_exclusion AS e WHERE e.source_key = d.source_key
  )
ORDER BY c.content_embedding <-> %s::vector
LIMIT 150
"""
_QUERY_WITH_CONTENT = _QUERY.replace(
    "SELECT c.id, c.sequence_number, d.type, d.id_",
    "SELECT c.content, c.sequence_number, d.type, d.id_, d.title",
)
_APPLICATION_NAME = "demo-vector-search-stress"


@dataclass(frozen=True)
class QueryResult:
    duration_ms: float
    rows: int
    error: str | None


@dataclass(frozen=True)
class LevelResult:
    concurrency: int
    rounds: int
    queries: int
    errors: int
    error_counts: dict[str, int]
    minimum_rows: int
    p50_rows: float
    p95_rows: float
    maximum_rows: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None
    wall_p95_ms: float
    client_cpu_percent: float


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _connection_kwargs(
    statement_timeout_seconds: float,
    connect_timeout_seconds: float,
    hnsw_ef_search: int | None = None,
    hnsw_iterative_scan: str | None = None,
) -> dict[str, Any]:
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing PostgreSQL environment variables: {', '.join(missing)}")
    timeout_ms = math.ceil(statement_timeout_seconds * 1000)
    options = [
        "-c default_transaction_read_only=on",
        f"-c statement_timeout={timeout_ms}",
        "-c idle_in_transaction_session_timeout=5000",
    ]
    if hnsw_ef_search is not None:
        options.append(f"-c hnsw.ef_search={hnsw_ef_search}")
    if hnsw_iterative_scan is not None:
        options.append(f"-c hnsw.iterative_scan={hnsw_iterative_scan}")
    return {
        "host": os.environ["PGHOST"],
        "port": int(os.environ["PGPORT"]),
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "password": os.environ["PGPASSWORD"],
        "application_name": _APPLICATION_NAME,
        "connect_timeout": math.ceil(connect_timeout_seconds),
        "options": " ".join(options),
        "autocommit": True,
    }


async def _fetch_string(cursor: psycopg.AsyncCursor[Any], query: sql.SQL) -> str:
    await cursor.execute(query)
    row = await cursor.fetchone()
    if row is None or not isinstance(row[0], str):
        raise RuntimeError(f"query did not return a string: {query}")
    return row[0]


async def _verify_read_only(
    connection_kwargs: dict[str, Any], *, require_readonly_role: bool
) -> None:
    async with (
        await psycopg.AsyncConnection.connect(**connection_kwargs) as connection,
        connection.cursor() as cursor,
    ):
        read_only = await _fetch_string(cursor, sql.SQL("SHOW transaction_read_only"))
        current_user = await _fetch_string(cursor, sql.SQL("SELECT current_user"))
    if read_only != "on":
        raise RuntimeError("server did not enforce transaction_read_only=on")
    if require_readonly_role and current_user != "readonly_user":
        raise RuntimeError(f"refusing non-readonly database role: {current_user}")


async def _load_vectors(connection_kwargs: dict[str, Any], count: int) -> tuple[str, ...]:
    query = sql.SQL(
        "SELECT content_embedding::text FROM document_content_chunk "
        "WHERE content_embedding IS NOT NULL ORDER BY id LIMIT {}"
    ).format(sql.Literal(count))
    async with (
        await psycopg.AsyncConnection.connect(**connection_kwargs) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(query)
        vectors = tuple(row[0] for row in await cursor.fetchall())
    if len(vectors) < count:
        raise RuntimeError(f"database has only {len(vectors)} usable vectors; {count} required")
    return vectors


async def _run_query(
    *,
    connection_kwargs: dict[str, Any],
    query: str,
    vector: str,
    server_execution_time: bool,
    gate: asyncio.Event,
    ready: asyncio.Event,
) -> QueryResult:
    connection: psycopg.AsyncConnection[Any] | None = None
    started_ns: int | None = None
    try:
        connection = await psycopg.AsyncConnection.connect(**connection_kwargs)
        ready.set()
        await gate.wait()
        started_ns = time.perf_counter_ns()
        async with connection.cursor() as cursor:
            executed_query = query
            if server_execution_time:
                executed_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
            await cursor.execute(cast(LiteralString, executed_query), (vector,))
            payload = await cursor.fetchall()
        duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        rows = len(payload)
        if server_execution_time:
            plan = cast(list[dict[str, Any]], payload[0][0])[0]
            duration_ms = float(plan["Execution Time"])
            rows = int(cast(dict[str, Any], plan["Plan"])["Actual Rows"])
        return QueryResult(duration_ms=duration_ms, rows=rows, error=None)
    except Exception as exc:
        ready.set()
        duration_ms = (
            (time.perf_counter_ns() - started_ns) / 1_000_000 if started_ns is not None else 0.0
        )
        error = type(exc).__name__
        if isinstance(exc, psycopg.Error):
            primary = exc.diag.message_primary or str(exc).splitlines()[0]
            error = f"{error}:{exc.sqlstate or 'no-sqlstate'}:{primary}"
        return QueryResult(duration_ms=duration_ms, rows=0, error=error)
    finally:
        if connection is not None:
            await connection.close()


async def _run_level(
    *,
    concurrency: int,
    rounds: int,
    vectors: tuple[str, ...],
    connection_kwargs: dict[str, Any],
    query: str,
    server_execution_time: bool,
) -> LevelResult:
    results: list[QueryResult] = []
    wall_durations: list[float] = []
    vector_offset = 0
    level_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    for _round in range(rounds):
        gate = asyncio.Event()
        ready = [asyncio.Event() for _ in range(concurrency)]
        tasks = [
            asyncio.create_task(
                _run_query(
                    connection_kwargs=connection_kwargs,
                    query=query,
                    vector=vectors[(vector_offset + index) % len(vectors)],
                    server_execution_time=server_execution_time,
                    gate=gate,
                    ready=event,
                )
            )
            for index, event in enumerate(ready)
        ]
        await asyncio.gather(*(event.wait() for event in ready))
        started_ns = time.perf_counter_ns()
        gate.set()
        round_results = await asyncio.gather(*tasks)
        wall_durations.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        results.extend(round_results)
        vector_offset += concurrency

    level_ended_ns = time.perf_counter_ns()
    cpu_ended_ns = time.process_time_ns()
    successful = [result.duration_ms for result in results if result.error is None]
    return LevelResult(
        concurrency=concurrency,
        rounds=rounds,
        queries=len(results),
        errors=sum(result.error is not None for result in results),
        error_counts=dict(Counter(result.error for result in results if result.error is not None)),
        minimum_rows=min(result.rows for result in results),
        p50_rows=_percentile([float(result.rows) for result in results], 0.50),
        p95_rows=_percentile([float(result.rows) for result in results], 0.95),
        maximum_rows=max(result.rows for result in results),
        p50_ms=_percentile(successful, 0.50) if successful else None,
        p95_ms=_percentile(successful, 0.95) if successful else None,
        p99_ms=_percentile(successful, 0.99) if successful else None,
        max_ms=max(successful) if successful else None,
        wall_p95_ms=_percentile(wall_durations, 0.95),
        client_cpu_percent=(cpu_ended_ns - cpu_started_ns)
        / (level_ended_ns - level_started_ns)
        * 100,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run -m app.stress.vector_search_burst",
        description="Run synchronized, read-only pgvector searches using existing vectors.",
    )
    parser.add_argument("--version", action="version", version="vector-search-burst 0.1")
    parser.add_argument(
        "--concurrency",
        action="append",
        type=int,
        required=True,
        help="concurrent SELECT queries; repeat for stepped levels",
    )
    parser.add_argument("--rounds", type=int, default=3, help="rounds per level; default: 3")
    parser.add_argument(
        "--statement-timeout-seconds",
        type=float,
        default=60,
        help="server-side timeout per SELECT; default: 60",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=10,
        help="connection establishment timeout; default: 10",
    )
    parser.add_argument(
        "--hnsw-ef-search",
        type=int,
        help="session-local HNSW candidate-list size; database default when omitted",
    )
    parser.add_argument(
        "--hnsw-iterative-scan",
        choices=("off", "relaxed_order", "strict_order"),
        help="session-local filtered HNSW scan mode; database default when omitted",
    )
    parser.add_argument(
        "--allow-remote", action="store_true", help="required when PGHOST is not localhost"
    )
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="return full chunk bodies; allowed only for localhost unless --server-execution-time",
    )
    parser.add_argument(
        "--server-execution-time",
        action="store_true",
        help="use EXPLAIN ANALYZE server execution time instead of client round-trip time",
    )
    parser.add_argument(
        "--read-only-ack",
        action="store_true",
        help="acknowledge intentional load against a remote read-only database",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    levels = tuple(args.concurrency)
    if any(level <= 0 for level in levels) or args.rounds <= 0:
        raise RuntimeError("concurrency and rounds must be positive")
    host = os.environ.get("PGHOST", "")
    is_remote = host not in {"localhost", "127.0.0.1", "::1"}
    if is_remote and not (args.allow_remote and args.read_only_ack):
        raise RuntimeError("remote database requires --allow-remote and --read-only-ack")
    if is_remote and args.include_content and not args.server_execution_time:
        raise RuntimeError(
            "remote --include-content requires --server-execution-time to avoid data transfer"
        )
    connection_kwargs = _connection_kwargs(
        args.statement_timeout_seconds,
        args.connect_timeout_seconds,
        args.hnsw_ef_search,
        args.hnsw_iterative_scan,
    )
    await _verify_read_only(connection_kwargs, require_readonly_role=is_remote)
    vectors = await _load_vectors(connection_kwargs, max(levels))
    query = _QUERY_WITH_CONTENT if args.include_content else _QUERY
    output: list[LevelResult] = []
    for concurrency in levels:
        result = await _run_level(
            concurrency=concurrency,
            rounds=args.rounds,
            vectors=vectors,
            connection_kwargs=connection_kwargs,
            query=query,
            server_execution_time=args.server_execution_time,
        )
        output.append(result)
        if not args.json:
            print(json.dumps(asdict(result), separators=(",", ":")), flush=True)
    if args.json:
        print(json.dumps({"schema_version": 1, "levels": [asdict(item) for item in output]}))
    return 1 if any(result.errors for result in output) else 0


def main() -> None:
    args = _build_parser().parse_args()
    try:
        exit_code = asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        exit_code = 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
