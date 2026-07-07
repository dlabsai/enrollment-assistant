import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("demo-va")
    logger.setLevel(logging.INFO)

    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        for handler in uvicorn_logger.handlers:
            logger.addHandler(handler)
        return logger

    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


logger = _get_logger()


def current_time_utc() -> datetime:
    return datetime.now(UTC)


def ensure_dir(dir_path: Path) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)


def configure_observability() -> None:
    """Configure app-owned observability hooks."""
