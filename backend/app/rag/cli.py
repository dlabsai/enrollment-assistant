from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from pydantic_core import ValidationError

from app.rag.utils import configure_logging

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.rag.pipeline import RagPipelineProgressSnapshot

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.cli", description="Run the Demo University RAG sync/build pipeline."
    )
    parser.add_argument("--version", action="version", version="demo-va rag cli")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--plain", action="store_true", help="Use plain logs instead of rich logs")

    subparsers = parser.add_subparsers(dest="command")
    sync_parser = subparsers.add_parser(
        "sync", help="Write the demo corpus and rebuild the search DB"
    )
    sync_parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sync_parser.add_argument(
        "--plain", action="store_true", help="Use plain logs instead of rich logs"
    )
    sync_parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Drop and recreate existing RAG documents/chunks/embeddings before rebuilding",
    )
    sync_parser.add_argument(
        "--job-name",
        default="rag_cli_sync",
        help="Job name used for logging and advisory-lock diagnostics",
    )
    return parser


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    normalized = list(argv)
    if not normalized:
        return ["sync"]

    if normalized[0] in {"-h", "--help", "--version"}:
        return normalized

    skip_next = False
    for argument in normalized:
        if skip_next:
            skip_next = False
            continue
        if argument == "--job-name":
            skip_next = True
            continue
        if argument.startswith("--job-name="):
            continue
        if argument in {"-h", "--help", "--version", "-v", "--verbose", "--plain"}:
            continue
        if argument == "sync":
            return normalized
        if argument.startswith("-"):
            continue
        return normalized

    return ["sync", *normalized]


async def _log_progress(snapshot: RagPipelineProgressSnapshot) -> None:
    statuses = ", ".join(f"{step.key}={step.status}" for step in snapshot.steps)
    current = f" current={snapshot.current_step}" if snapshot.current_step else ""
    logger.info(
        "RAG progress: %s/%s finished%s (%s)",
        snapshot.finished_steps,
        snapshot.total_steps,
        current,
        statuses,
    )


async def _run_sync(*, job_name: str, force_rebuild: bool) -> None:
    from app.rag.pipeline import run_rag_sync_pipeline  # noqa: PLC0415

    await run_rag_sync_pipeline(
        job_name=job_name,
        progress_callback=_log_progress,
        force_rebuild=force_rebuild,
        job_trigger="cli",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))

    configure_logging(level=logging.DEBUG if args.verbose else logging.INFO, rich=not args.plain)

    if args.command != "sync":
        parser.error(f"Unknown command: {args.command}")

    try:
        asyncio.run(_run_sync(job_name=args.job_name, force_rebuild=args.force_rebuild))
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 130
    except ValidationError as exc:
        logger.critical("Invalid configuration: %s", exc)
        return 2
    except Exception:
        logger.exception("RAG sync failed")
        return 1

    logger.info("RAG sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
