"""Background eval jobs and run registry for API callers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.chat.evals.chatbot import run_chatbot_evaluation
from app.chat.evals.guardrails import run_guardrails_evaluation
from app.evals.rag_data import create_session_factory
from app.evals.run_tracking import (
    ActiveEvalRunExistsError,
    create_eval_run,
    heartbeat_eval_run,
    publish_eval_run_event,
)
from app.evals.runtime import EvalRunConfig, EvalRunRequestConfig, EvalSuite
from app.evals.storage import eval_run_config_payload, save_eval_report, threshold_failed_case_names
from app.evals.test_db import (
    create_test_db_engine,
    initialize_test_db_schema,
    load_and_migrate_eval_database,
    prepare_test_db_engine,
)
from app.otel import otel_export_scope, otel_session_factory_scope, wait_for_pending_spans

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from app.evals.report import EvaluationReport


@dataclass(frozen=True)
class EvalRunPaths:
    """Filesystem locations used by one eval run."""

    logs_dir: Path


RunSuite = Callable[[EvalRunConfig], Awaitable["EvaluationReport[Any, Any, Any]"]]


class EvalRunAlreadyRunningError(RuntimeError):
    """Raised when a user attempts to start a second active eval run."""


class EvalRunNotFoundError(RuntimeError):
    """Raised when an eval run is not owned by this worker and user."""


class EvalRunJob:
    """Background eval job whose lifetime is independent of browser SSE connections."""

    def __init__(
        self,
        config: EvalRunRequestConfig,
        *,
        paths: EvalRunPaths,
        user_id: UUID | None,
        on_complete: Callable[[EvalRunJob], None] | None = None,
    ) -> None:
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid4().hex
        self.config = config
        self.user_id = user_id
        self.started_at = datetime.now(UTC)
        self.log_id = (
            f"eval_run_{config.suite.value}_"
            f"{self.started_at.strftime('%Y-%m-%d_%H-%M-%S')}_{self.run_id}.log"
        )
        self.log_path = paths.logs_dir / self.log_id
        self.status = "start"
        self._task: asyncio.Task[None] | None = None
        self._engine: Any | None = None
        self._on_complete = on_complete
        self._completion_notified = False
        self._persisted = False
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def enable_persistence(self) -> None:
        if self.user_id is None or self._persisted:
            return
        await create_eval_run(
            run_id=self.run_id,
            user_id=self.user_id,
            suite=self.config.suite.value,
            initial_payload={
                "status": "start",
                "suite": self.config.suite.value,
                "run_id": self.run_id,
            },
        )
        self._persisted = True

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_suite())
        if self._persisted:
            self._heartbeat_task = asyncio.create_task(self._watch_persisted_status())

    async def _watch_persisted_status(self) -> None:
        while self._task is not None and not self._task.done():
            await asyncio.sleep(2)
            try:
                status = await heartbeat_eval_run(self.run_id)
            except Exception:
                logger.exception("Failed to heartbeat eval run %s", self.run_id)
                continue
            if status != "start":
                self._task.cancel()
                return

    async def cancel(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    def _append_log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")

    async def _publish(self, event: str, payload: dict[str, object]) -> None:
        if self._persisted:
            await publish_eval_run_event(self.run_id, event, payload)

    def _notify_complete(self) -> None:
        if self._completion_notified:
            return
        self._completion_notified = True
        if self._on_complete is not None:
            self._on_complete(self)

    async def _finish(self, status: str, *, error_message: str | None = None) -> None:
        self.status = status
        payload: dict[str, object] = {"status": status, "run_id": self.run_id}
        if error_message is not None:
            payload["message"] = error_message
        try:
            await self._publish("status", payload)
        finally:
            self._notify_complete()

    async def _emit_log(self, message: str) -> None:
        self._append_log(message)
        await self._publish("log", {"message": message, "run_id": self.run_id})

    async def _progress_handler(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        case_name = event.get("case_name")
        run_index = event.get("run_index")
        if event_type == "case_start" and isinstance(case_name, str):
            await self._emit_log(f"Started {case_name} run {run_index}")
            await self._publish("case_start", {**dict(event), "run_id": self.run_id})
            return

        if event_type == "case_complete" and isinstance(case_name, str):
            duration = event.get("duration")
            passed = event.get("passed")
            status = "passed" if passed is True else "failed"
            if isinstance(duration, int | float):
                await self._emit_log(
                    f"Finished {case_name} run {run_index}: {status} ({duration:.1f}s)"
                )
            else:
                await self._emit_log(f"Finished {case_name} run {run_index}: {status}")
            await self._publish("case_complete", {**dict(event), "run_id": self.run_id})

    async def _run_suite(self) -> None:
        try:
            runner = _get_suite_runner(self.config.suite)
            if self.config.instructions is not None:
                await self._emit_log(f"Using {self.config.instructions.display_name}")
            await self._emit_log("Configuring and migrating guarded eval database")
            database_url = await asyncio.to_thread(load_and_migrate_eval_database)
            if self.config.suite is EvalSuite.GUARDRAILS:
                await self._emit_log(
                    "Preparing eval database; guardrails evals do not use RAG data"
                )
                self._engine = create_test_db_engine(database_url)
                await initialize_test_db_schema(self._engine)
            else:
                await self._emit_log("Preparing eval database and RAG data")
                self._engine = await prepare_test_db_engine(
                    rebuild_rag=self.config.rebuild_rag, database_url=database_url
                )
            session_factory = create_session_factory(self._engine)
            with otel_session_factory_scope(session_factory), otel_export_scope(enabled=True):
                run_config = EvalRunConfig(
                    session_factory=session_factory,
                    suite=self.config.suite,
                    repeat=self.config.repeat,
                    max_concurrency=self.config.max_concurrency,
                    test_cases=self.config.test_cases,
                    case_payloads=self.config.case_payloads,
                    instructions=self.config.instructions,
                    pass_threshold=self.config.pass_threshold,
                    rebuild_rag=self.config.rebuild_rag,
                    chatbot_model=self.config.chatbot_model,
                    guardrail_model=self.config.guardrail_model,
                    evaluation_model=self.config.evaluation_model,
                    progress_handler=self._progress_handler,
                )
                report = await runner(run_config)

                failed = threshold_failed_case_names(report, self.config.pass_threshold)
                status = "threshold_failed" if failed else "complete"
                report_record = await save_eval_report(
                    session_factory,
                    report,
                    suite=self.config.suite.value,
                    pass_threshold=self.config.pass_threshold,
                    status=status,
                    log_id=self.log_id,
                    config=eval_run_config_payload(self.config),
                )
                await self._emit_log(f"Report stored in eval database: {report_record.report_id}")
                await self._publish(
                    "report",
                    {
                        "report_id": report_record.report_id,
                        "name": report_record.name,
                        "generated_at": report_record.generated_at.isoformat(),
                        "repeats": report_record.repeats,
                        "concurrency": report_record.max_concurrency,
                        "run_id": self.run_id,
                    },
                )

                if failed:
                    summary = ", ".join(failed)
                    message = f"Failed {len(failed)}/{len(report.cases)} cases: {summary}"
                    await self._emit_log(f"Failed threshold: {summary}")
                    with contextlib.suppress(Exception):
                        await self._publish("error", {"message": message, "run_id": self.run_id})
                    await self._finish("error", error_message=message)
                    return

                await self._finish("complete")
        except asyncio.CancelledError:
            self._append_log("Eval run cancelled")
            with contextlib.suppress(Exception):
                await self._publish("log", {"message": "Eval run cancelled", "run_id": self.run_id})
            await self._finish("cancelled")
            raise
        except Exception as error:
            message = str(error)
            self._append_log(message)
            with contextlib.suppress(Exception):
                await self._publish("log", {"message": message, "run_id": self.run_id})
                await self._publish("error", {"message": message, "run_id": self.run_id})
            await self._finish("error", error_message=message)
        finally:
            if self._engine is not None:
                await wait_for_pending_spans()
                await self._engine.dispose()
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
                self._heartbeat_task = None


class EvalRunManager:
    """Starts persisted eval runs and tracks only tasks owned by this worker."""

    def __init__(self) -> None:
        self._runs: dict[str, EvalRunJob] = {}

    async def start_run(
        self, config: EvalRunRequestConfig, *, paths: EvalRunPaths, user_id: UUID
    ) -> EvalRunJob:
        job = EvalRunJob(config, paths=paths, user_id=user_id, on_complete=self._remove_run)
        try:
            await job.enable_persistence()
        except ActiveEvalRunExistsError as error:
            raise EvalRunAlreadyRunningError(str(error)) from error
        self._runs[job.run_id] = job
        job.start()
        return job

    def get_run(self, run_id: str, *, user_id: UUID) -> EvalRunJob:
        job = self._runs.get(run_id)
        if job is None or job.user_id != user_id:
            raise EvalRunNotFoundError("Eval run not found")
        return job

    def _remove_run(self, job: EvalRunJob) -> None:
        self._runs.pop(job.run_id, None)


EVAL_RUN_MANAGER = EvalRunManager()


def _get_suite_runner(suite: EvalSuite) -> RunSuite:
    if suite is EvalSuite.CHATBOT:
        return run_chatbot_evaluation
    if suite is EvalSuite.GUARDRAILS:
        return run_guardrails_evaluation
    raise ValueError(f"Unsupported eval suite: {suite}")
