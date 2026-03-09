"""SQLAlchemy event-based SQL query capture."""

from __future__ import annotations

import inspect
import json
import linecache
import reprlib
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from types import FrameType
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
    expose_raw_params: bool = False
    redacted_param_keys: tuple[str, ...] = (
        "password",
        "passwd",
        "token",
        "secret",
        "api_key",
        "apikey",
    )
    max_queries_per_request: int = 1000
    max_sql_length: int = 5000
    max_params_length: int = 500
    capture_callsite: bool = False
    capture_callsite_stack: bool = True
    capture_callsite_context: bool = False
    callsite_context_max_lines: int = 60
    callsite_max_frames: int = 80
    callsite_exclude_substrings: tuple[str, ...] = (
        "fastapi_silk_profiler/sql_capture.py",
        "site-packages/sqlalchemy",
    )


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


def _truncate_text(value: str, max_len: int) -> tuple[str, bool]:
    """Truncate text to max length, returning (text, was_truncated)."""
    if max_len <= 0:
        return "", bool(value)
    if len(value) <= max_len:
        return value, False
    if max_len <= 3:
        return value[:max_len], True
    return f"{value[:max_len - 3]}...", True


def _canonicalize_for_signature(value: object) -> object:
    """Normalize params into JSON-serializable canonical structure."""
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_for_signature(inner)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_for_signature(inner) for inner in value]
    if isinstance(value, set):
        normalized_items = [_canonicalize_for_signature(inner) for inner in value]
        return sorted(normalized_items, key=lambda inner: json.dumps(inner, sort_keys=True))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _params_signature(parameters: object) -> str:
    """Build stable signature for duplicate/N+1 grouping."""
    normalized = _canonicalize_for_signature(parameters)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _format_callsite_stack(frames: list[str]) -> list[str]:
    """Format frame list in a pyinstrument-like tree shape."""
    if not frames:
        return []
    if len(frames) == 1:
        return frames
    formatted = [frames[0]]
    for depth, frame_text in enumerate(frames[1:], start=1):
        formatted.append(f"{'   ' * (depth - 1)}└─ {frame_text}")
    return formatted


def _build_callsite_stack(
    frame: FrameType,
    options: SQLCaptureOptions,
) -> list[str]:
    """Build call stack from app frames for one SQL query."""
    excluded = options.callsite_exclude_substrings
    max_frames = options.callsite_max_frames
    if max_frames <= 0:
        return []

    stack: list[str] = []
    current: FrameType | None = frame
    while current is not None and len(stack) < max_frames:
        filename = current.f_code.co_filename
        normalized = filename.replace("\\", "/")
        if any(token in normalized for token in excluded):
            current = current.f_back
            continue
        lineno = current.f_lineno
        function_name = current.f_code.co_name
        stack.append(f"{filename}:{lineno} in {function_name}")
        current = current.f_back
    stack.reverse()
    return _format_callsite_stack(stack)


def _detect_callsite(
    options: SQLCaptureOptions | None,
) -> tuple[str, str, list[str], int | None, list[str]]:
    """Return best-effort origin, source line, context and call stack from frames."""
    active_options = options if options is not None else SQLCaptureOptions()
    frame = inspect.currentframe()
    if frame is None:
        return "", "", [], None, []
    excluded = active_options.callsite_exclude_substrings
    try:
        current = frame.f_back
        while current is not None:
            filename = current.f_code.co_filename
            normalized = filename.replace("\\", "/")
            if any(token in normalized for token in excluded):
                current = current.f_back
                continue
            lineno = current.f_lineno
            function_name = current.f_code.co_name
            origin = f"{filename}:{lineno} in {function_name}"
            code_line = linecache.getline(filename, lineno).strip()
            stack_lines = (
                _build_callsite_stack(current, active_options)
                if active_options.capture_callsite_stack
                else []
            )
            if not active_options.capture_callsite_context:
                return origin, code_line, [], None, stack_lines
            try:
                source_lines, start_line = inspect.getsourcelines(current)
            except (OSError, TypeError):
                return origin, code_line, [], None, stack_lines

            cleaned_lines = [line.rstrip("\n") for line in source_lines]
            raw_highlight = lineno - start_line
            if raw_highlight < 0:
                raw_highlight = 0
            if raw_highlight >= len(cleaned_lines):
                raw_highlight = len(cleaned_lines) - 1 if cleaned_lines else 0

            max_lines = active_options.callsite_context_max_lines
            if max_lines <= 0 or len(cleaned_lines) <= max_lines:
                highlight_line = raw_highlight + 1 if cleaned_lines else None
                return origin, code_line, cleaned_lines, highlight_line, stack_lines

            half = max_lines // 2
            start_index = max(0, raw_highlight - half)
            end_index = min(len(cleaned_lines), start_index + max_lines)
            if end_index - start_index < max_lines:
                start_index = max(0, end_index - max_lines)
            clipped = cleaned_lines[start_index:end_index]
            clipped_highlight = raw_highlight - start_index + 1
            return origin, code_line, clipped, clipped_highlight, stack_lines
        return "", "", [], None, []
    finally:
        del frame


def _sanitize_params(parameters: object, options: SQLCaptureOptions | None) -> tuple[str, bool]:
    """Return privacy-safe params representation for one SQL statement."""
    max_params_len = options.max_params_length if options is not None else 500
    if options is not None and options.expose_raw_params:
        return _truncate_text(_safe_repr(parameters, max_len=max_params_len), max_params_len)

    if isinstance(parameters, dict):
        lowered_keys = (
            tuple(token.lower() for token in options.redacted_param_keys)
            if options is not None
            else SQLCaptureOptions().redacted_param_keys
        )
        masked: dict[object, object] = {}
        for key, value in parameters.items():
            key_text = str(key).lower()
            should_mask = any(token in key_text for token in lowered_keys)
            masked[key] = "***" if should_mask else value
        return _truncate_text(_safe_repr(masked, max_len=max_params_len), max_params_len)

    return _truncate_text(_safe_repr(parameters, max_len=max_params_len), max_params_len)


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
    max_queries = options.max_queries_per_request if options is not None else 1000
    if len(collector) >= max_queries:
        timings.pop()
        return
    previous_statement, started = timings.pop()
    max_sql_len = options.max_sql_length if options is not None else 5000
    statement_text, sql_truncated = _truncate_text(previous_statement, max_sql_len)
    params_text, params_truncated = _sanitize_params(parameters, options)
    callsite, callsite_code, callsite_context, callsite_highlight_line, callsite_stack = (
        _detect_callsite(options)
        if options is not None and options.capture_callsite
        else ("", "", [], None, [])
    )
    record = SQLQueryRecord(
        statement=statement_text,
        params=params_text,
        duration_ms=(perf_counter() - started) * 1000,
        rowcount=getattr(cursor, "rowcount", None),
        callsite=callsite,
        callsite_code=callsite_code,
        callsite_stack=callsite_stack,
        callsite_context=callsite_context,
        callsite_highlight_line=callsite_highlight_line,
        params_signature=_params_signature(parameters),
        sql_truncated=sql_truncated,
        params_truncated=params_truncated,
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
