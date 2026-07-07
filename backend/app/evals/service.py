"""In-process eval runner shared by API routes and future CLIs."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.chat.evals.chatbot import run_chatbot_evaluation
from app.chat.evals.guardrails import run_guardrails_evaluation
from app.evals.rag_data import create_session_factory
from app.evals.runtime import EvalRunConfig, EvalRunRequestConfig, EvalSuite
from app.evals.storage import eval_run_config_payload, save_eval_report, threshold_failed_case_names
from app.evals.test_db import (
    create_test_db_engine,
    initialize_test_db_schema,
    load_and_migrate_eval_database,
    prepare_test_db_engine,
)
from app.otel import otel_export_scope, otel_session_factory_scope, wait_for_pending_spans

if TYPE_CHECKING:
    from pathlib import Path

    from app.evals.report import EvaluationReport


@dataclass(frozen=True)
class EvalRunPaths:
    """Filesystem locations used by one eval run."""

    logs_dir: Path


@dataclass(frozen=True)
class EvalRunEvent:
    """Structured event emitted by the in-process eval runner."""

    event: str
    payload: dict[str, object]


@dataclass(frozen=True)
class EvalRunSnapshot:
    """Current observable state for one API-started eval run."""

    run_id: str
    user_id: UUID | None
    suite: str
    status: str
    report_id: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


RunSuite = Callable[[EvalRunConfig], Awaitable["EvaluationReport[Any, Any, Any]"]]


class EvalRunAlreadyRunningError(RuntimeError):
    """Raised when a user attempts to start a second active eval run."""


class EvalRunNotFoundError(RuntimeError):
    """Raised when an eval run id is unknown to the in-memory runner."""


class EvalRunJob:
    """Background eval job whose lifetime is independent of SSE subscribers."""

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
        self.paths = paths
        self.user_id = user_id
        self.started_at = datetime.now(UTC)
        self.completed_at: datetime | None = None
        self.log_id = (
            f"eval_run_{config.suite.value}_"
            f"{self.started_at.strftime('%Y-%m-%d_%H-%M-%S')}_{self.run_id}.log"
        )
        self.log_path = paths.logs_dir / self.log_id
        self.status = "start"
        self.report_id: str | None = None
        self.error_message: str | None = None
        self._events: list[EvalRunEvent] = []
        self._subscribers: set[asyncio.Queue[EvalRunEvent | None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._engine: Any | None = None
        self._on_complete = on_complete
        self._completion_notified = False
        self._publish(
            EvalRunEvent(
                "status", {"status": "start", "suite": config.suite.value, "run_id": self.run_id}
            )
        )

    @property
    def is_active(self) -> bool:
        return self.status == "start"

    def snapshot(self) -> EvalRunSnapshot:
        return EvalRunSnapshot(
            run_id=self.run_id,
            user_id=self.user_id,
            suite=self.config.suite.value,
            status=self.status,
            report_id=self.report_id,
            error_message=self.error_message,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_suite())

    async def cancel(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def subscribe(self) -> AsyncGenerator[EvalRunEvent]:
        queue: asyncio.Queue[EvalRunEvent | None] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        replay_events = list(self._events)
        for event in replay_events:
            yield event
        if not self.is_active:
            self._subscribers.discard(queue)
            return
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._subscribers.discard(queue)

    def _append_log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")

    def _publish(self, event: EvalRunEvent) -> None:
        self._events.append(event)
        stale_subscribers: list[asyncio.Queue[EvalRunEvent | None]] = []
        for subscriber in self._subscribers:
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                stale_subscribers.append(subscriber)
        for subscriber in stale_subscribers:
            self._disconnect_slow_subscriber(subscriber)

    def _disconnect_slow_subscriber(self, subscriber: asyncio.Queue[EvalRunEvent | None]) -> None:
        """Wake a subscriber that cannot keep up instead of leaving it waiting forever."""
        self._subscribers.discard(subscriber)
        while True:
            try:
                subscriber.get_nowait()
            except asyncio.QueueEmpty:
                break
        subscriber.put_nowait(
            EvalRunEvent(
                "error",
                {
                    "message": "Eval stream fell behind; reconnect to resume live updates",
                    "run_id": self.run_id,
                },
            )
        )
        subscriber.put_nowait(None)

    def _close_subscriber(self, subscriber: asyncio.Queue[EvalRunEvent | None]) -> None:
        """Send a terminal marker, making room if the queue is full."""
        self._subscribers.discard(subscriber)
        while True:
            try:
                subscriber.put_nowait(None)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    subscriber.get_nowait()
            else:
                return

    def _notify_complete(self) -> None:
        if self._completion_notified:
            return
        self._completion_notified = True
        if self._on_complete is not None:
            self._on_complete(self)

    def _finish(self, status: str, *, error_message: str | None = None) -> None:
        self.status = status
        self.error_message = error_message
        self.completed_at = datetime.now(UTC)
        payload: dict[str, object] = {"status": status, "run_id": self.run_id}
        if error_message is not None:
            payload["message"] = error_message
        self._publish(EvalRunEvent("status", payload))
        for subscriber in list(self._subscribers):
            self._close_subscriber(subscriber)
        self._notify_complete()

    async def _emit_log(self, message: str) -> None:
        self._append_log(message)
        self._publish(EvalRunEvent("log", {"message": message, "run_id": self.run_id}))

    async def _progress_handler(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        case_name = event.get("case_name")
        run_index = event.get("run_index")
        if event_type == "case_start" and isinstance(case_name, str):
            await self._emit_log(f"Started {case_name} run {run_index}")
            self._publish(EvalRunEvent("case_start", {**dict(event), "run_id": self.run_id}))
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
            self._publish(EvalRunEvent("case_complete", {**dict(event), "run_id": self.run_id}))

    async def _run_suite(self) -> None:
        try:
            runner = _get_suite_runner(self.config.suite)
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
                self.report_id = report_record.report_id
                await self._emit_log(f"Report stored in eval database: {report_record.report_id}")
                self._publish(
                    EvalRunEvent(
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
                )

                if failed:
                    summary = ", ".join(failed)
                    message = f"Failed {len(failed)}/{len(report.cases)} cases: {summary}"
                    await self._emit_log(f"Failed threshold: {summary}")
                    self._publish(
                        EvalRunEvent("error", {"message": message, "run_id": self.run_id})
                    )
                    self._finish("error", error_message=message)
                    return

                self._finish("complete")
        except asyncio.CancelledError:
            self._append_log("Eval run cancelled")
            self._publish(
                EvalRunEvent("log", {"message": "Eval run cancelled", "run_id": self.run_id})
            )
            self._finish("cancelled")
            raise
        except Exception as error:
            message = str(error)
            await self._emit_log(message)
            self._publish(EvalRunEvent("error", {"message": message, "run_id": self.run_id}))
            self._finish("error", error_message=message)
        finally:
            if self._engine is not None:
                await wait_for_pending_spans()
                await self._engine.dispose()


class EvalRunManager:
    """In-memory registry for active/recent API eval runs."""

    def __init__(
        self, *, completed_ttl: timedelta = timedelta(hours=6), max_completed_runs: int = 50
    ) -> None:
        self._runs: dict[str, EvalRunJob] = {}
        self._current_by_user: dict[UUID, str] = {}
        self._completed_ttl = completed_ttl
        self._max_completed_runs = max_completed_runs
        self._prune_task: asyncio.Task[None] | None = None

    def start_run(
        self, config: EvalRunRequestConfig, *, paths: EvalRunPaths, user_id: UUID
    ) -> EvalRunJob:
        self._prune_completed()
        current = self.current_run(user_id)
        if current is not None and current.is_active:
            raise EvalRunAlreadyRunningError("An eval run is already running")
        job = EvalRunJob(config, paths=paths, user_id=user_id, on_complete=self._on_job_complete)
        self._runs[job.run_id] = job
        self._current_by_user[user_id] = job.run_id
        job.start()
        return job

    def current_run(self, user_id: UUID) -> EvalRunJob | None:
        self._prune_completed()
        run_id = self._current_by_user.get(user_id)
        return self._runs.get(run_id) if run_id is not None else None

    def get_run(self, run_id: str, *, user_id: UUID) -> EvalRunJob:
        self._prune_completed()
        job = self._runs.get(run_id)
        if job is None or job.user_id != user_id:
            raise EvalRunNotFoundError("Eval run not found")
        return job

    def _on_job_complete(self, _job: EvalRunJob) -> None:
        self._prune_completed()
        self._schedule_prune()

    def _schedule_prune(self) -> None:
        if self._prune_task is not None and not self._prune_task.done():
            return
        self._prune_task = asyncio.create_task(self._delayed_prune())

    async def _delayed_prune(self) -> None:
        try:
            await asyncio.sleep(self._completed_ttl.total_seconds())
            self._prune_completed()
        finally:
            self._prune_task = None

    def _prune_completed(self) -> None:
        if not self._runs:
            return

        now = datetime.now(UTC)
        completed_jobs = [job for job in self._runs.values() if not job.is_active]
        run_ids_to_remove = {
            job.run_id
            for job in completed_jobs
            if job.completed_at is not None and now - job.completed_at >= self._completed_ttl
        }

        retained_completed_jobs = [
            job for job in completed_jobs if job.run_id not in run_ids_to_remove
        ]
        retained_completed_jobs.sort(
            key=lambda job: job.completed_at or job.started_at, reverse=True
        )
        for job in retained_completed_jobs[self._max_completed_runs :]:
            run_ids_to_remove.add(job.run_id)

        for run_id in run_ids_to_remove:
            self._runs.pop(run_id, None)

        if run_ids_to_remove:
            self._current_by_user = {
                user_id: run_id
                for user_id, run_id in self._current_by_user.items()
                if run_id not in run_ids_to_remove
            }

    def clear(self) -> None:
        self._runs.clear()
        self._current_by_user.clear()
        if self._prune_task is not None:
            self._prune_task.cancel()
            self._prune_task = None


EVAL_RUN_MANAGER = EvalRunManager()


def _get_suite_runner(suite: EvalSuite) -> RunSuite:
    if suite is EvalSuite.CHATBOT:
        return run_chatbot_evaluation
    if suite is EvalSuite.GUARDRAILS:
        return run_guardrails_evaluation
    raise ValueError(f"Unsupported eval suite: {suite}")


async def run_eval_in_process(
    config: EvalRunRequestConfig, *, paths: EvalRunPaths
) -> AsyncGenerator[EvalRunEvent]:
    """Run an eval suite in-process and emit SSE-friendly events."""
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    log_id = (
        f"eval_run_{config.suite.value}_"
        f"{datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S')}_{uuid4().hex}.log"
    )
    log_path = paths.logs_dir / log_id

    def append_log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")

    yield EvalRunEvent("status", {"status": "start", "suite": config.suite.value})

    queue: asyncio.Queue[EvalRunEvent | None] = asyncio.Queue(maxsize=100)
    engine = None

    async def emit_log(message: str) -> None:
        append_log(message)
        await queue.put(EvalRunEvent("log", {"message": message}))

    async def progress_handler(event: dict[str, Any]) -> None:
        event_type = event.get("type")
        case_name = event.get("case_name")
        run_index = event.get("run_index")
        if event_type == "case_start" and isinstance(case_name, str):
            await emit_log(f"Started {case_name} run {run_index}")
            await queue.put(EvalRunEvent("case_start", dict(event)))
            return

        if event_type == "case_complete" and isinstance(case_name, str):
            duration = event.get("duration")
            passed = event.get("passed")
            status = "passed" if passed is True else "failed"
            if isinstance(duration, int | float):
                await emit_log(f"Finished {case_name} run {run_index}: {status} ({duration:.1f}s)")
            else:
                await emit_log(f"Finished {case_name} run {run_index}: {status}")
            await queue.put(EvalRunEvent("case_complete", dict(event)))

    async def run_suite() -> None:
        nonlocal engine
        try:
            runner = _get_suite_runner(config.suite)
            await emit_log("Configuring and migrating guarded eval database")
            database_url = await asyncio.to_thread(load_and_migrate_eval_database)
            if config.suite is EvalSuite.GUARDRAILS:
                await emit_log("Preparing eval database; guardrails evals do not use RAG data")
                engine = create_test_db_engine(database_url)
                await initialize_test_db_schema(engine)
            else:
                await emit_log("Preparing eval database and RAG data")
                engine = await prepare_test_db_engine(
                    rebuild_rag=config.rebuild_rag, database_url=database_url
                )
            session_factory = create_session_factory(engine)
            with otel_session_factory_scope(session_factory), otel_export_scope(enabled=True):
                run_config = EvalRunConfig(
                    session_factory=session_factory,
                    suite=config.suite,
                    repeat=config.repeat,
                    max_concurrency=config.max_concurrency,
                    test_cases=config.test_cases,
                    case_payloads=config.case_payloads,
                    pass_threshold=config.pass_threshold,
                    rebuild_rag=config.rebuild_rag,
                    chatbot_model=config.chatbot_model,
                    guardrail_model=config.guardrail_model,
                    evaluation_model=config.evaluation_model,
                    progress_handler=progress_handler,
                )
                report = await runner(run_config)

                failed = threshold_failed_case_names(report, config.pass_threshold)
                status = "threshold_failed" if failed else "complete"
                report_record = await save_eval_report(
                    session_factory,
                    report,
                    suite=config.suite.value,
                    pass_threshold=config.pass_threshold,
                    status=status,
                    log_id=log_id,
                    config=eval_run_config_payload(config),
                )
                await emit_log(f"Report stored in eval database: {report_record.report_id}")
                await queue.put(
                    EvalRunEvent(
                        "report",
                        {
                            "report_id": report_record.report_id,
                            "name": report_record.name,
                            "generated_at": report_record.generated_at.isoformat(),
                            "repeats": report_record.repeats,
                            "concurrency": report_record.max_concurrency,
                        },
                    )
                )

                if failed:
                    summary = ", ".join(failed)
                    await emit_log(f"Failed threshold: {summary}")
                    await queue.put(
                        EvalRunEvent(
                            "error",
                            {
                                "message": (
                                    f"Failed {len(failed)}/{len(report.cases)} cases: {summary}"
                                )
                            },
                        )
                    )
                    await queue.put(EvalRunEvent("status", {"status": "error"}))
                    return

                await queue.put(EvalRunEvent("status", {"status": "complete"}))
        except asyncio.CancelledError:
            append_log("Eval run cancelled")
            raise
        except Exception as error:
            await emit_log(str(error))
            await queue.put(EvalRunEvent("error", {"message": str(error)}))
            await queue.put(EvalRunEvent("status", {"status": "error"}))
        finally:
            if engine is not None:
                await wait_for_pending_spans()
                await engine.dispose()
            current_task = asyncio.current_task()
            if current_task is None or current_task.cancelling() == 0:
                await queue.put(None)

    task = asyncio.create_task(run_suite())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
