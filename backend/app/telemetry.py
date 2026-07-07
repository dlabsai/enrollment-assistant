from __future__ import annotations

import logging
from functools import wraps
from string import Formatter
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Span, SpanKind

from app.otel_genai import start_span

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from contextlib import AbstractContextManager

logger = logging.getLogger("demo-va")
_formatter = Formatter()


def _format_message(template: str, attributes: Mapping[str, Any]) -> str:
    values: dict[str, str] = {}
    for _, field_name, _, _ in _formatter.parse(template):
        if field_name is None:
            continue
        if field_name.endswith("="):
            key = field_name[:-1]
            if key in attributes:
                values[field_name] = f"{key}={attributes[key]}"
            continue
        if field_name in attributes:
            values[field_name] = str(attributes[field_name])
    try:
        return template.format_map(_SafeFormatMap(values))
    except Exception:
        return template


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def span(
    name: str, *, _span_kind: SpanKind = SpanKind.INTERNAL, **attributes: Any
) -> AbstractContextManager[Span]:
    return start_span(
        _format_message(name, attributes), kind=_span_kind, attributes=attributes or None
    )


def info(message: str, **attributes: Any) -> None:
    logger.info(_format_message(message, attributes))


def error(message: str, **attributes: Any) -> None:
    logger.error(_format_message(message, attributes))


def instrument() -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with start_span(f"Calling {func.__module__}.{func.__name__}"):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
