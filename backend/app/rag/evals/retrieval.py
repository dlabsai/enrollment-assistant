"""Deterministic retrieval baseline runner for RAG source regression cases."""

# The runner intentionally reuses chat tool DB helpers so evals exercise runtime retrieval
# semantics.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.chat.tools import document as document_tools
from app.chat.tools.models import DocumentTitleResult, FindDocumentChunksResultItem
from app.chat.tools.utils import get_azure_openai_client
from app.core.config import settings
from app.models import DocumentType
from app.rag.constants import EMBEDDING_MODEL, EMBEDDING_VECTOR_DIMENSIONS

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_CASES_PATH = Path(__file__).with_name("retrieval_cases.json")
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports" / "rag"
SUMMARY_HIT_AT_5 = 5
SUMMARY_HIT_AT_10 = 10
GROUNDING_DOCUMENT_TYPES = tuple(DocumentType)

SourcePolicy = Literal["any_required_or_acceptable", "all_required"]


def _empty_int_list() -> list[int]:
    return []


def _empty_string_list() -> list[str]:
    return []


def _empty_expected_source_list() -> list[ExpectedSource]:
    return []


class ExpectedSource(BaseModel):
    """Expected or forbidden source for a retrieval case."""

    type: DocumentType
    id: int
    title: str | None = None
    sequence_numbers: list[int] = Field(default_factory=_empty_int_list)


class RetrievalPassCriteria(BaseModel):
    """Binary pass criteria for one retrieval case."""

    source_hit_at_k: int = 10
    expected_terms_in_top_k: int = 10
    forbidden_source_miss_at_k: int = 10
    source_policy: SourcePolicy = "any_required_or_acceptable"


class RetrievalEvalCase(BaseModel):
    """One source-grounded retrieval regression case."""

    id: str
    query: str
    audience: Literal["internal", "public"] = "internal"
    source: Literal["prod_feedback", "prod_trace", "manual_regression", "synthetic"]
    feedback_ids: list[str] = Field(default_factory=_empty_string_list)
    failure_mode: str | None = None
    regression: bool = True
    document_types: list[DocumentType] | None = None
    required_sources: list[ExpectedSource] = Field(default_factory=_empty_expected_source_list)
    acceptable_sources: list[ExpectedSource] = Field(default_factory=_empty_expected_source_list)
    forbidden_sources: list[ExpectedSource] = Field(default_factory=_empty_expected_source_list)
    expected_terms: list[str] = Field(default_factory=_empty_string_list)
    pass_criteria: RetrievalPassCriteria = Field(default_factory=RetrievalPassCriteria)
    notes: str | None = None


class RetrievalDataset(BaseModel):
    """Retrieval eval dataset fixture."""

    name: str
    description: str | None = None
    version: int
    cases: list[RetrievalEvalCase]


class SourceOccurrence(BaseModel):
    """A source found in a result list."""

    type: DocumentType
    id: int
    title: str | None = None
    rank: int
    sequence_numbers: list[int] = Field(default_factory=_empty_int_list)
    result_kind: Literal["chunk", "title"]


class RetrievalRunReport(BaseModel):
    """Full JSON report for a retrieval baseline/experiment run."""

    report_name: str
    generated_at: datetime
    dataset_name: str
    dataset_version: int
    case_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    config: dict[str, Any]
    cases: list[dict[str, Any]]


def _load_dataset(path: Path) -> RetrievalDataset:
    return RetrievalDataset.model_validate_json(path.read_text())


def _source_ref(source: ExpectedSource) -> str:
    return f"{source.type.value}:{source.id}"


def _source_key(source_type: DocumentType, source_id: int) -> str:
    return f"{source_type.value}:{source_id}"


def _make_database_url_from_pg_env() -> str:
    missing = [name for name in ("PGHOST", "PGUSER", "PGDATABASE") if not os.environ.get(name)]
    if missing:
        missing_text = ", ".join(missing)
        raise SystemExit(f"Missing PG env var(s): {missing_text}")

    return str(
        URL.create(
            "postgresql+psycopg",
            username=os.environ["PGUSER"],
            password=os.environ.get("PGPASSWORD") or None,
            host=os.environ["PGHOST"],
            port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ["PGDATABASE"],
        )
    )


def _resolve_database_url(database_url: str | None, *, use_pg_env: bool) -> str:
    if database_url and use_pg_env:
        raise SystemExit("Use either --database-url or --use-pg-env, not both")
    if use_pg_env:
        return _make_database_url_from_pg_env()
    if database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://")
    return str(settings.SQLALCHEMY_DATABASE_URI)


def _redact_database_url(database_url: str) -> str:
    if "@" not in database_url or "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    _auth, host = rest.split("@", 1)
    return f"{scheme}://***@{host}"


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _chunk_sources_at_rank(
    result: FindDocumentChunksResultItem, *, rank: int
) -> list[SourceOccurrence]:
    occurrences: list[SourceOccurrence] = []
    for source_type_text, source_entries in result.sources.items():
        source_type = DocumentType(source_type_text)
        for source_id, sequence_numbers, title in source_entries:
            occurrences.append(
                SourceOccurrence(
                    type=source_type,
                    id=source_id,
                    title=title,
                    rank=rank,
                    sequence_numbers=sequence_numbers,
                    result_kind="chunk",
                )
            )
    return occurrences


def _title_source_at_rank(result: DocumentTitleResult, *, rank: int) -> SourceOccurrence:
    return SourceOccurrence(
        type=result.type,
        id=result.id,
        title=result.title,
        rank=rank,
        sequence_numbers=[],
        result_kind="title",
    )


def _grounding_document_types_for_case(case: RetrievalEvalCase) -> list[DocumentType]:
    if case.document_types is None:
        return list(GROUNDING_DOCUMENT_TYPES)
    return case.document_types


def _first_hit_by_source(occurrences: Iterable[SourceOccurrence]) -> dict[str, SourceOccurrence]:
    first_hits: dict[str, SourceOccurrence] = {}
    for occurrence in occurrences:
        key = _source_key(occurrence.type, occurrence.id)
        existing = first_hits.get(key)
        if existing is None or occurrence.rank < existing.rank:
            first_hits[key] = occurrence
    return first_hits


def _sources_within_k(
    first_hits: dict[str, SourceOccurrence], sources: Iterable[ExpectedSource], *, k: int
) -> dict[str, int | None]:
    ranks: dict[str, int | None] = {}
    for source in sources:
        key = _source_ref(source)
        hit = first_hits.get(key)
        ranks[key] = hit.rank if hit is not None and hit.rank <= k else None
    return ranks


def _term_hits(
    results: list[FindDocumentChunksResultItem], terms: list[str], *, k: int
) -> dict[str, bool]:
    top_text = "\n".join(result.content for result in results[:k]).casefold()
    return {term: term.casefold() in top_text for term in terms}


def _source_policy_pass(
    *,
    first_hits: dict[str, SourceOccurrence],
    required_sources: list[ExpectedSource],
    acceptable_sources: list[ExpectedSource],
    k: int,
    policy: SourcePolicy,
) -> tuple[bool, dict[str, Any]]:
    required_ranks = _sources_within_k(first_hits, required_sources, k=k)
    acceptable_ranks = _sources_within_k(first_hits, acceptable_sources, k=k)
    enforced = bool(required_ranks or acceptable_ranks)

    if not enforced:
        passed = True
    elif policy == "all_required":
        passed = bool(required_ranks) and all(rank is not None for rank in required_ranks.values())
    else:
        relevant_ranks = [*required_ranks.values(), *acceptable_ranks.values()]
        passed = any(rank is not None for rank in relevant_ranks)

    return passed, {
        "policy": policy,
        "k": k,
        "enforced": enforced,
        "required_ranks": required_ranks,
        "acceptable_ranks": acceptable_ranks,
    }


def _sequence_number_diagnostics(
    occurrences: Iterable[SourceOccurrence], sources: Iterable[ExpectedSource], *, k: int
) -> list[dict[str, Any]]:
    occurrence_list = [occurrence for occurrence in occurrences if occurrence.rank <= k]
    diagnostics: list[dict[str, Any]] = []
    for source in sources:
        expected_sequences = set(source.sequence_numbers)
        if not expected_sequences:
            continue
        matched_sequences: set[int] = set()
        matched_ranks: set[int] = set()
        for occurrence in occurrence_list:
            if occurrence.type != source.type or occurrence.id != source.id:
                continue
            overlap = expected_sequences.intersection(occurrence.sequence_numbers)
            if overlap:
                matched_sequences.update(overlap)
                matched_ranks.add(occurrence.rank)
        diagnostics.append(
            {
                "source": _source_ref(source),
                "expected_sequence_numbers": sorted(expected_sequences),
                "matched_sequence_numbers": sorted(matched_sequences),
                "matched_ranks": sorted(matched_ranks),
                "passed": bool(matched_sequences),
            }
        )
    return diagnostics


def _forbidden_pass(
    *, case: RetrievalEvalCase, combined_hits: dict[str, SourceOccurrence]
) -> tuple[bool, dict[str, int | None]]:
    ranks = _sources_within_k(
        combined_hits, case.forbidden_sources, k=case.pass_criteria.forbidden_source_miss_at_k
    )
    return all(rank is None for rank in ranks.values()), ranks


def _expected_terms_pass(
    *, case: RetrievalEvalCase, chunk_results: list[FindDocumentChunksResultItem]
) -> tuple[bool, dict[str, bool]]:
    hits = _term_hits(
        chunk_results, case.expected_terms, k=case.pass_criteria.expected_terms_in_top_k
    )
    return all(hits.values()), hits


def _chunk_results_out(results: list[FindDocumentChunksResultItem]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "content_snippet": _truncate(result.content, 700),
            "sources": result.sources,
        }
        for index, result in enumerate(results, start=1)
    ]


def _title_results_out(results: list[DocumentTitleResult]) -> list[dict[str, Any]]:
    return [
        {"rank": index, "type": result.type.value, "id": result.id, "title": result.title}
        for index, result in enumerate(results, start=1)
    ]


def _source_title_matches(expected: ExpectedSource, occurrence: SourceOccurrence) -> bool:
    if expected.title is None or occurrence.title is None:
        return True
    return expected.title.casefold() in occurrence.title.casefold()


def _chunk_source_diagnostics(
    chunk_hits: dict[str, SourceOccurrence],
    title_hits: dict[str, SourceOccurrence],
    case: RetrievalEvalCase,
) -> tuple[bool, dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    passed = True
    for source in [*case.required_sources, *case.acceptable_sources]:
        key = _source_ref(source)
        chunk_hit = chunk_hits.get(key)
        title_hit = title_hits.get(key)
        source_passed = True
        if chunk_hit is not None:
            source_passed = _source_title_matches(source, chunk_hit)
        elif title_hit is not None:
            source_passed = _source_title_matches(source, title_hit)
        if not source_passed:
            passed = False
        diagnostics.append(
            {
                "source": key,
                "chunk_rank": chunk_hit.rank if chunk_hit else None,
                "title_rank": title_hit.rank if title_hit else None,
                "passed": source_passed,
            }
        )
    return passed, {"sources": diagnostics}


async def _run_case(
    session: AsyncSession, openai: AsyncOpenAI, case: RetrievalEvalCase, *, read_only: bool
) -> dict[str, Any]:
    if read_only:
        await session.execute(text("SET TRANSACTION READ ONLY"))

    started = perf_counter()
    is_internal = case.audience == "internal"
    grounding_document_types = _grounding_document_types_for_case(case)
    chunk_payload = await document_tools._find_document_chunks_db(  # noqa: SLF001
        session,
        openai,
        case.query,
        is_internal=is_internal,
        document_types=grounding_document_types,
    )
    title_results = await document_tools._find_document_titles_db(  # noqa: SLF001
        session,
        openai,
        case.query,
        is_internal=is_internal,
        document_types=grounding_document_types,
    )
    duration = perf_counter() - started

    chunk_occurrences = [
        occurrence
        for rank, result in enumerate(chunk_payload.result, start=1)
        for occurrence in _chunk_sources_at_rank(result, rank=rank)
    ]
    title_occurrences = [
        _title_source_at_rank(result, rank=rank)
        for rank, result in enumerate(title_results, start=1)
    ]
    chunk_hits = _first_hit_by_source(chunk_occurrences)
    title_hits = _first_hit_by_source(title_occurrences)
    grounding_occurrences = [*chunk_occurrences, *title_occurrences]
    grounding_hits = _first_hit_by_source(grounding_occurrences)

    criteria = case.pass_criteria
    source_discovery_ok, source_discovery_details = _source_policy_pass(
        first_hits=grounding_hits,
        required_sources=case.required_sources,
        acceptable_sources=case.acceptable_sources,
        k=criteria.source_hit_at_k,
        policy=criteria.source_policy,
    )
    chunk_source_ok, chunk_source_details = _chunk_source_diagnostics(chunk_hits, title_hits, case)
    sequence_diagnostics = {
        "k": criteria.source_hit_at_k,
        "required": _sequence_number_diagnostics(
            chunk_occurrences, case.required_sources, k=criteria.source_hit_at_k
        ),
        "acceptable": _sequence_number_diagnostics(
            chunk_occurrences, case.acceptable_sources, k=criteria.source_hit_at_k
        ),
    }
    terms_ok, term_details = _expected_terms_pass(case=case, chunk_results=chunk_payload.result)
    forbidden_ok, forbidden_details = _forbidden_pass(case=case, combined_hits=grounding_hits)
    passed = source_discovery_ok and terms_ok and forbidden_ok and chunk_source_ok

    return {
        "id": case.id,
        "query": case.query,
        "audience": case.audience,
        "source": case.source,
        "feedback_ids": case.feedback_ids,
        "failure_mode": case.failure_mode,
        "regression": case.regression,
        "document_types": [doc_type.value for doc_type in case.document_types]
        if case.document_types is not None
        else None,
        "grounding_document_types": [doc_type.value for doc_type in grounding_document_types],
        "notes": case.notes,
        "duration_seconds": round(duration, 3),
        "passed": passed,
        "assertions": {
            "source_discovery_pass": source_discovery_ok,
            "expected_terms_pass": terms_ok,
            "forbidden_sources_pass": forbidden_ok,
            "chunk_source_pass": chunk_source_ok,
        },
        "metrics": {
            "source_discovery": source_discovery_details,
            "chunk_source": chunk_source_details | {"passed": chunk_source_ok},
            "sequence_numbers": sequence_diagnostics,
            "expected_terms": {
                "k": case.pass_criteria.expected_terms_in_top_k,
                "hits": term_details,
            },
            "forbidden_sources": {
                "k": case.pass_criteria.forbidden_source_miss_at_k,
                "ranks": forbidden_details,
            },
            "source_hits": {
                "required": _hit_summary(grounding_hits, case.required_sources),
                "acceptable": _hit_summary(grounding_hits, case.acceptable_sources),
                "forbidden": _hit_summary(grounding_hits, case.forbidden_sources),
            },
        },
        "expected": {
            "required_sources": [
                source.model_dump(mode="json") for source in case.required_sources
            ],
            "acceptable_sources": [
                source.model_dump(mode="json") for source in case.acceptable_sources
            ],
            "forbidden_sources": [
                source.model_dump(mode="json") for source in case.forbidden_sources
            ],
            "expected_terms": case.expected_terms,
        },
        "raw_results": {
            "chunks": _chunk_results_out(chunk_payload.result),
            "titles": _title_results_out(title_results),
        },
    }


def _hit_summary(
    hits: dict[str, SourceOccurrence], expected_sources: list[ExpectedSource]
) -> dict[str, dict[str, Any] | None]:
    summary: dict[str, dict[str, Any] | None] = {}
    for source in expected_sources:
        key = _source_ref(source)
        hit = hits.get(key)
        summary[key] = hit.model_dump(mode="json") if hit is not None else None
    return summary


async def run(
    *,
    cases_path: Path,
    output_path: Path,
    summary_output_path: Path | None = None,
    database_url: str | None = None,
    use_pg_env: bool = False,
    case_ids: set[str] | None = None,
    read_only: bool = True,
) -> RetrievalRunReport:
    dataset = _load_dataset(cases_path)
    cases = [case for case in dataset.cases if case_ids is None or case.id in case_ids]
    resolved_database_url = _resolve_database_url(database_url, use_pg_env=use_pg_env)
    engine = create_async_engine(resolved_database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    openai = get_azure_openai_client()
    case_reports: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(cases, start=1):
            print(f"[{index}/{len(cases)}] {case.id}: {case.query}")
            async with session_factory() as session:
                case_report = await _run_case(session, openai, case, read_only=read_only)
                await session.rollback()
            case_reports.append(case_report)
            status = "PASS" if case_report["passed"] else "FAIL"
            assertions = case_report["assertions"]
            print(
                "    "
                f"{status} discovery={assertions['source_discovery_pass']} "
                f"terms={assertions['expected_terms_pass']} "
                f"forbidden={assertions['forbidden_sources_pass']} "
                f"duration={case_report['duration_seconds']}s"
            )
    finally:
        await openai.close()
        await engine.dispose()

    passed_count = sum(1 for case in case_reports if case["passed"])
    report = RetrievalRunReport(
        report_name=output_path.stem,
        generated_at=datetime.now(UTC),
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        case_count=len(case_reports),
        passed_count=passed_count,
        failed_count=len(case_reports) - passed_count,
        pass_rate=round(passed_count / len(case_reports), 4) if case_reports else 0.0,
        config={
            "cases_path": str(cases_path),
            "database_url": _redact_database_url(resolved_database_url),
            "read_only": read_only,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": EMBEDDING_VECTOR_DIMENSIONS,
            "catalog_content_policy": "available_in_document_search",
            "chunk_top_k": document_tools._FIND_DOCUMENT_CHUNKS_MAX_RESULTS,  # noqa: SLF001
            "title_top_k": document_tools._FIND_DOCUMENT_TITLES_MAX_RESULTS,  # noqa: SLF001
        },
        cases=case_reports,
    )

    await asyncio.to_thread(_write_report, output_path, report)
    if summary_output_path is not None:
        await asyncio.to_thread(_write_summary_report, summary_output_path, report)
    return report


def _parse_case_ids(value: str | None) -> set[str] | None:
    if value is None or value.strip() == "":
        return None
    return {case_id.strip() for case_id in value.split(",") if case_id.strip()}


def _default_output_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORTS_DIR / f"rag-retrieval-baseline-{stamp}.json"


def _write_report(path: Path, report: RetrievalRunReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _first_non_null_rank(ranks: dict[str, int | None]) -> int | None:
    hit_ranks = [rank for rank in ranks.values() if rank is not None]
    return min(hit_ranks) if hit_ranks else None


def _case_summary(case_report: dict[str, Any]) -> dict[str, Any]:
    source_metrics = case_report["metrics"]["source_discovery"]
    required_ranks = source_metrics["required_ranks"]
    acceptable_ranks = source_metrics["acceptable_ranks"]
    expected_terms = case_report["metrics"]["expected_terms"]["hits"]
    forbidden_ranks = case_report["metrics"]["forbidden_sources"]["ranks"]
    missing_terms = [term for term, hit in expected_terms.items() if not hit]
    forbidden_hits = {source: rank for source, rank in forbidden_ranks.items() if rank is not None}
    first_source_rank = _first_non_null_rank({**required_ranks, **acceptable_ranks})
    sequence_metrics = case_report["metrics"].get("sequence_numbers", {})
    required_sequence_miss_sources = [
        entry["source"] for entry in sequence_metrics.get("required", []) if not entry["passed"]
    ]

    return {
        "id": case_report["id"],
        "query": case_report["query"],
        "passed": case_report["passed"],
        "assertions": case_report["assertions"],
        "failure_mode": case_report["failure_mode"],
        "document_types": case_report["document_types"],
        "grounding_document_types": case_report["grounding_document_types"],
        "source_policy": source_metrics["policy"],
        "source_hit_at_k": source_metrics["k"],
        "source_discovery_enforced": source_metrics["enforced"],
        "first_source_rank": first_source_rank,
        "required_ranks": required_ranks,
        "acceptable_ranks": acceptable_ranks,
        "missing_terms": missing_terms,
        "forbidden_hits": forbidden_hits,
        "required_sequence_miss_sources": required_sequence_miss_sources,
    }


def _portable_config(config: dict[str, Any]) -> dict[str, Any]:
    portable = dict(config)
    portable.pop("database_url", None)
    cases_path = portable.get("cases_path")
    if isinstance(cases_path, str):
        path = Path(cases_path)
        if path.is_absolute():
            backend_root = Path(__file__).resolve().parents[3]
            try:
                portable["cases_path"] = str(path.relative_to(backend_root))
            except ValueError:
                portable["cases_path"] = path.name
    return portable


def _rank_bucket(rank: int | None, *, enforced: bool) -> str:
    if not enforced:
        return "not_applicable"
    if rank is None:
        return "miss"
    if rank <= SUMMARY_HIT_AT_5:
        return "hit_at_5"
    if rank <= SUMMARY_HIT_AT_10:
        return "hit_at_10"
    return "hit_after_10"


def _failure_document_type_buckets(case_summary: dict[str, Any]) -> list[str]:
    grounding_document_types = case_summary["grounding_document_types"]
    return grounding_document_types or ["all_document_types"]


def _summary_report(report: RetrievalRunReport) -> dict[str, Any]:
    case_summaries = [_case_summary(case_report) for case_report in report.cases]
    assertion_failures: Counter[str] = Counter()
    failure_modes: Counter[str] = Counter()
    document_type_failures: Counter[str] = Counter()
    rank_buckets: defaultdict[str, int] = defaultdict(int)

    for case in case_summaries:
        if not case["passed"]:
            failure_modes[case["failure_mode"] or "unknown"] += 1
            for assertion_name, passed in case["assertions"].items():
                if not passed:
                    assertion_failures[assertion_name] += 1
            for document_type in _failure_document_type_buckets(case):
                document_type_failures[document_type] += 1

        rank_buckets[
            _rank_bucket(case["first_source_rank"], enforced=case["source_discovery_enforced"])
        ] += 1

    return {
        "dataset_name": report.dataset_name,
        "dataset_version": report.dataset_version,
        "case_count": report.case_count,
        "passed_count": report.passed_count,
        "failed_count": report.failed_count,
        "pass_rate": report.pass_rate,
        "config": _portable_config(report.config),
        "aggregate_failures": {
            "assertions": dict(assertion_failures),
            "failure_modes": dict(failure_modes),
            "document_types": dict(document_type_failures),
            "source_rank_buckets": dict(sorted(rank_buckets.items())),
        },
        "cases": case_summaries,
    }


def _write_summary_report(path: Path, report: RetrievalRunReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_json = json.dumps(_summary_report(report), indent=2, ensure_ascii=False)
    path.write_text(f"{summary_json}\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out", type=Path, default=_default_output_path())
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="Optional compact JSON summary path suitable for source control.",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--use-pg-env", action="store_true")
    parser.add_argument("--case-ids", default=None, help="Comma-separated case IDs to run")
    parser.add_argument(
        "--allow-writes", action="store_true", help="Do not set retrieval sessions to READ ONLY."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run(
            cases_path=args.cases,
            output_path=args.out,
            summary_output_path=args.summary_out,
            database_url=args.database_url,
            use_pg_env=args.use_pg_env,
            case_ids=_parse_case_ids(args.case_ids),
            read_only=not args.allow_writes,
        )
    )


if __name__ == "__main__":
    main()
