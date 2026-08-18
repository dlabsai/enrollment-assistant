from __future__ import annotations

import logging
from uuid import uuid4

from app.rag.build_notifications import RagBuildLogHandler


def test_pipeline_log_handler_only_publishes_its_build_context() -> None:
    published: list[tuple[str, dict[str, object]]] = []

    class Publisher:
        def publish_nowait(self, event: str, payload: dict[str, object]) -> None:
            published.append((event, payload))

    handler = RagBuildLogHandler(Publisher())  # type: ignore[arg-type]
    job_id = uuid4()
    record = logging.LogRecord(
        name="app.rag.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="build message",
        args=(),
        exc_info=None,
    )

    handler.emit(record)
    matching_token = handler.bind(job_id)
    other_handler = RagBuildLogHandler(Publisher())  # type: ignore[arg-type]
    other_token = other_handler.bind(uuid4())
    try:
        handler.emit(record)
    finally:
        other_handler.unbind(other_token)

    try:
        handler.emit(record)
    finally:
        handler.unbind(matching_token)

    assert published == [
        ("log", {"job_id": str(job_id), "stream": "stdout", "message": "build message"})
    ]
