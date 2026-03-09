"""SQLAlchemy event-based SQL query capture."""

from __future__ import annotations

import reprlib
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Protocol, cast

from sqlalchemy import event
from sqlalchemy.engine import Engine

from .models import SQLQueryRecord

_CAPTURED_SQL: ContextVar[list[SQLQueryRecord] | None] = ContextVar("captured_sql", default=None)
_CAPTURE_OPTIONS: ContextVar[SQLCaptureOptions | None] = ContextVar(
    "capture_options",
    default=None,
)
_LISTENER_LOCK = Lock()
_LISTENERS_REGISTERED = False


@dataclass(slots=True)
class SQLCaptureOptions:
    """Behavior switches for SQL capture hooks."""

    capture_explain: bool = False
    explain_max_statements_per_request: int = 20


@dataclass(slots=True)
class SQLCaptureToken:
    """Context tokens needed to stop SQL capture."""

    collector_token: Token[list[SQLQueryRecord] | None]
    options_token: Token[SQLCaptureOptions | None]


class _ConnectionWithInfo(Protocol):
    """Protocol for SQLAlchemy connection objects used in event hooks."""

    info: dict[str, object]
    dialect: object

    def exec_driver_sql(self, statement: str, parameters: object = ...) -> object:
        """Execute SQL directly through SQLAlchemy connection."""


class _CursorWithRowCount(Protocol):
    """Protocol for DBAPI cursor objects used in event hooks."""

    rowcount: int | None


class _ResultWithFetchAll(Protocol):
    """Protocol for SQLAlchemy execute result."""

    def fetchall(self) -> list[tuple[object, ...]]:
        """Fetch all result rows."""


class _ExceptionContextWithConnection(Protocol):
    """Protocol for SQLAlchemy handle_error exception context."""

    connection: _ConnectionWithInfo | None


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
    if cast(bool, conn.info.get("_silk_explain_active", False)):
        return
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
    if cast(bool, conn.info.get("_silk_explain_active", False)):
        return
    del statement, context, executemany
    collector = _CAPTURED_SQL.get()
    options = _CAPTURE_OPTIONS.get()
    timings = cast(
        list[tuple[str, float]],
        conn.info.get("_silk_query_timings", []),
    )
    if collector is None or not timings:
        return
    previous_statement, started = timings.pop()
    record = SQLQueryRecord(
        statement=previous_statement,
        params=_safe_repr(parameters),
        duration_ms=(perf_counter() - started) * 1000,
        rowcount=getattr(cursor, "rowcount", None),
    )
    if options is not None and options.capture_explain:
        record.explain_plan = _capture_explain_plan(
            conn=conn,
            statement=previous_statement,
            parameters=parameters,
            max_statements=options.explain_max_statements_per_request,
        )
    collector.append(record)


def _handle_error(exception_context: _ExceptionContextWithConnection) -> None:
    """Drop stale timing frame when a SQL execution fails.

    SQLAlchemy emits ``before_cursor_execute`` for statements that fail, but
    ``after_cursor_execute`` does not run for those failures. Without popping
    the timing frame here, the next successful query can read stale timing data.
    """
    conn = exception_context.connection
    if conn is None:
        return
    if cast(bool, conn.info.get("_silk_explain_active", False)):
        return
    timings = cast(
        list[tuple[str, float]],
        conn.info.get("_silk_query_timings", []),
    )
    if timings:
        timings.pop()


def _capture_explain_plan(
    conn: _ConnectionWithInfo,
    statement: str,
    parameters: object,
    max_statements: int,
) -> list[str]:
    """Capture EXPLAIN rows for supported dialects and query shapes."""
    if max_statements <= 0:
        return []
    explain_count = cast(int, conn.info.get("_silk_explain_count", 0))
    if explain_count >= max_statements:
        return []
    dialect_name = getattr(conn.dialect, "name", "")
    normalized_statement = statement.lstrip().lower()
    if not (normalized_statement.startswith("select") or normalized_statement.startswith("with")):
        return []
    if dialect_name not in {"sqlite", "postgresql"}:
        return []
    conn.info["_silk_explain_active"] = True
    try:
        explain_sql = (
            f"EXPLAIN QUERY PLAN {statement}"
            if dialect_name == "sqlite"
            else f"EXPLAIN (FORMAT TEXT) {statement}"
        )
        result = cast(
            _ResultWithFetchAll,
            conn.exec_driver_sql(explain_sql, parameters),
        )
        rows = result.fetchall()
        if dialect_name == "sqlite":
            plan_lines = [", ".join(str(part) for part in row) for row in rows]
        else:
            plan_lines = [
                (", ".join(str(part) for part in row) if len(row) > 1 else str(row[0]))
                if row
                else ""
                for row in rows
            ]
        conn.info["_silk_explain_count"] = explain_count + 1
        return plan_lines
    except Exception:
        return []
    finally:
        conn.info["_silk_explain_active"] = False


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
        event.listen(Engine, "handle_error", _handle_error)
        _LISTENERS_REGISTERED = True


def start_sql_capture(
    options: SQLCaptureOptions | None = None,
) -> tuple[list[SQLQueryRecord], SQLCaptureToken]:
    """Start SQL capture for current request context.

    Returns:
        tuple[list[SQLQueryRecord], SQLCaptureToken]: Collector and reset token bundle.
    """
    collector: list[SQLQueryRecord] = []
    active_options = options if options is not None else SQLCaptureOptions()
    collector_token = _CAPTURED_SQL.set(collector)
    options_token = _CAPTURE_OPTIONS.set(active_options)
    return collector, SQLCaptureToken(collector_token=collector_token, options_token=options_token)


def stop_sql_capture(token: SQLCaptureToken) -> None:
    """Stop SQL capture for current request context.

    Args:
        token: Token returned by start_sql_capture.
    """
    _CAPTURED_SQL.reset(token.collector_token)
    _CAPTURE_OPTIONS.reset(token.options_token)
