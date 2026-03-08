"""SQLAlchemy event-based SQL query capture."""

from __future__ import annotations

import reprlib
from contextvars import ContextVar, Token
from threading import Lock
from time import perf_counter
from typing import Protocol, cast

from sqlalchemy import event
from sqlalchemy.engine import Engine

from .models import SQLQueryRecord

_CAPTURED_SQL: ContextVar[list[SQLQueryRecord] | None] = ContextVar("captured_sql", default=None)
_LISTENER_LOCK = Lock()
_LISTENERS_REGISTERED = False


class _ConnectionWithInfo(Protocol):
    """Protocol for SQLAlchemy connection objects used in event hooks."""

    info: dict[str, object]


class _CursorWithRowCount(Protocol):
    """Protocol for DBAPI cursor objects used in event hooks."""

    rowcount: int | None


def _safe_repr(value: object, max_len: int = 500) -> str:
    """Create a bounded string representation for SQL params.

    Args:
        value: Value to represent.
        max_len: Maximum output length.

    Returns:
        str: Safe string representation.
    """
    helper = reprlib.Repr()
    helper.maxstring = max_len
    helper.maxother = max_len
    return helper.repr(value)


def _before_cursor_execute(
    conn: _ConnectionWithInfo,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Track query start time."""
    del cursor, parameters, context, executemany
    timings = cast(
        list[tuple[str, float]],
        conn.info.setdefault("_silk_query_timings", []),
    )
    timings.append((statement, perf_counter()))


def _after_cursor_execute(
    conn: _ConnectionWithInfo,
    cursor: _CursorWithRowCount,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Capture query details after execution."""
    del statement, context, executemany
    collector = _CAPTURED_SQL.get()
    timings = cast(
        list[tuple[str, float]],
        conn.info.get("_silk_query_timings", []),
    )
    if collector is None or not timings:
        return
    previous_statement, started = timings.pop()
    collector.append(
        SQLQueryRecord(
            statement=previous_statement,
            params=_safe_repr(parameters),
            duration_ms=(perf_counter() - started) * 1000,
            rowcount=getattr(cursor, "rowcount", None),
        )
    )


def ensure_sqlalchemy_hooks() -> None:
    """Register SQLAlchemy listeners once for global capture."""
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return
    with _LISTENER_LOCK:
        if _LISTENERS_REGISTERED:
            return
        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
        _LISTENERS_REGISTERED = True


def start_sql_capture() -> tuple[list[SQLQueryRecord], Token[list[SQLQueryRecord] | None]]:
    """Start SQL capture for current request context.

    Returns:
        tuple[list[SQLQueryRecord], Token[list[SQLQueryRecord] | None]]: Collector and reset token.
    """
    collector: list[SQLQueryRecord] = []
    token = _CAPTURED_SQL.set(collector)
    return collector, token


def stop_sql_capture(token: Token[list[SQLQueryRecord] | None]) -> None:
    """Stop SQL capture for current request context.

    Args:
        token: Token returned by start_sql_capture.
    """
    _CAPTURED_SQL.reset(token)
