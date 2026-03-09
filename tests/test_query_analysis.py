"""Unit tests for query analysis and related rendering/capture helpers."""

from __future__ import annotations

from dataclasses import replace

from fastapi_silk_profiler.config import DashboardUIConfig
from fastapi_silk_profiler.models import ProfileReport, SQLQueryRecord
from fastapi_silk_profiler.query_analysis import QueryAnalysisConfig, analyze_queries, normalize_sql
from fastapi_silk_profiler.renderers import render_reports_dashboard, render_text
from fastapi_silk_profiler.sql_capture import (
    SQLCaptureOptions,
    _after_cursor_execute,
    _before_cursor_execute,
    _capture_explain_plan,
    _handle_error,
    _params_signature,
    start_sql_capture,
    stop_sql_capture,
)


class _FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeConnection:
    def __init__(self, *, dialect_name: str, fail: bool = False) -> None:
        self.info: dict[str, object] = {}
        self.dialect = _FakeDialect(dialect_name)
        self._fail = fail

    def exec_driver_sql(self, statement: str, parameters: object = None) -> _FakeResult:
        del statement, parameters
        if self._fail:
            raise RuntimeError("boom")
        return _FakeResult([(0, 0, 0, "SCAN items")])


class _FakeCursor:
    rowcount = 1


class _FakeExceptionContext:
    def __init__(self, connection: _FakeConnection | None) -> None:
        self.connection = connection


def test_analyze_queries_marks_expected_flags() -> None:
    queries = [
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE id = :id",
            params="{'id': 1}",
            duration_ms=4,
            rowcount=1,
        ),
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE id = :id",
            params="{'id': 1}",
            duration_ms=4,
            rowcount=1,
        ),
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE id = :id",
            params="{'id': 2}",
            duration_ms=2,
            rowcount=1,
        ),
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE id = :id",
            params="{'id': 3}",
            duration_ms=2,
            rowcount=1,
        ),
    ]
    summary = analyze_queries(
        queries=queries,
        request_duration_ms=16,
        config=QueryAnalysisConfig(
            enabled=True,
            slow_query_threshold_ms=3,
            duplicate_min_occurrences=2,
            n_plus_one_min_occurrences=3,
        ),
    )

    assert (
        normalize_sql("SELECT *  FROM items WHERE id = 123")
        == "select * from items where id = ?"
    )
    assert summary.total_db_time_ms == 12
    assert summary.db_time_ratio == 0.75
    assert summary.slow_query_count == 2
    assert summary.duplicate_query_count == 2
    assert summary.n_plus_one_query_count == 4
    assert queries[0].is_duplicate is True
    assert queries[2].is_n_plus_one is True


def test_normalize_sql_sqlparse_mode_strips_comments_and_normalizes() -> None:
    statement = "SELECT  *  FROM items /* noise */ WHERE id = 42 -- tail"
    normalized = normalize_sql(statement, mode="sqlparse")
    assert normalized == "select * from items where id = ?"


def test_analyze_queries_supports_sqlparse_normalization_mode() -> None:
    queries = [
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE id = 1",
            params="{}",
            params_signature="{}",
            duration_ms=1,
            rowcount=1,
        ),
        SQLQueryRecord(
            statement="select * from items where id = 2 -- comment",
            params="{}",
            params_signature="{}",
            duration_ms=1,
            rowcount=1,
        ),
    ]
    summary = analyze_queries(
        queries=queries,
        request_duration_ms=4,
        config=QueryAnalysisConfig(
            enabled=True,
            duplicate_min_occurrences=2,
            n_plus_one_min_occurrences=3,
            normalization_mode="sqlparse",
        ),
    )

    assert summary.duplicate_query_count == 2
    assert queries[0].normalized_statement == "select * from items where id = ?"
    assert queries[1].normalized_statement == "select * from items where id = ?"


def test_analyze_queries_uses_stable_param_signatures_for_duplicate_detection() -> None:
    queries = [
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE a = :a AND b = :b",
            params="{'a': 1, 'b': 2}",
            params_signature='{"a":1,"b":2}',
            duration_ms=2,
            rowcount=1,
        ),
        SQLQueryRecord(
            statement="SELECT * FROM items WHERE a = :a AND b = :b",
            params="{'b': 2, 'a': 1}",
            params_signature='{"a":1,"b":2}',
            duration_ms=3,
            rowcount=1,
        ),
    ]
    summary = analyze_queries(
        queries=queries,
        request_duration_ms=8,
        config=QueryAnalysisConfig(
            enabled=True,
            duplicate_min_occurrences=2,
            n_plus_one_min_occurrences=3,
        ),
    )

    assert summary.duplicate_query_count == 2
    assert summary.duplicate_query_groups == 1
    assert all(query.is_duplicate for query in queries)


def test_renderers_include_query_analysis_flags_and_explain() -> None:
    report = ProfileReport(
        method="GET",
        path="/items",
        status_code=200,
        duration_ms=20,
        sql_queries=[
            SQLQueryRecord(
                statement="select 1",
                params="{}",
                duration_ms=10,
                rowcount=1,
                is_slow=True,
                is_duplicate=True,
                is_n_plus_one=True,
                explain_plan=["SCAN items"],
            )
        ],
    )
    report.query_analysis = replace(
        report.query_analysis,
        total_db_time_ms=10,
        db_time_ratio=0.5,
        slow_query_count=1,
        duplicate_query_count=1,
        n_plus_one_query_count=1,
    )

    text_payload = render_text(report)
    html_payload = render_reports_dashboard(
        [report],
        report,
        "/_silk/reports",
        "/_silk/reports/clear",
    )

    assert "flags=slow,duplicate,n+1" in text_payload
    assert "EXPLAIN: SCAN items" in text_payload
    assert "Flags" in html_payload
    assert "EXPLAIN" in html_payload
    assert "badge-slow" in html_payload
    assert "badge-duplicate" in html_payload
    assert "badge-nplus1" in html_payload
    assert "Top Slow Query Offenders" in html_payload
    assert "Top Duplicate Query Offenders" in html_payload
    assert "N+1 Query Groups (Collapsed)" in html_payload


def test_renderers_show_empty_group_cards_without_flags() -> None:
    report = ProfileReport(
        method="GET",
        path="/items",
        status_code=200,
        duration_ms=20,
        sql_queries=[
            SQLQueryRecord(statement="select 1", params="{}", duration_ms=1, rowcount=1),
        ],
    )

    html_payload = render_reports_dashboard(
        [report],
        report,
        "/_silk/reports",
        "/_silk/reports/clear",
    )

    assert "No slow queries flagged." in html_payload
    assert "No duplicate query groups flagged." in html_payload
    assert "No N+1 patterns flagged." in html_payload


def test_capture_explain_plan_branch_guards_and_failures() -> None:
    sqlite_conn = _FakeConnection(dialect_name="sqlite")
    sqlite_conn.info["_silk_explain_count"] = 1
    assert _capture_explain_plan(sqlite_conn, "select 1", (), 0) == []
    assert _capture_explain_plan(sqlite_conn, "select 1", (), 1) == []

    pg_conn = _FakeConnection(dialect_name="postgresql")
    assert _capture_explain_plan(pg_conn, "select 1", (), 5) == ["0, 0, 0, SCAN items"]

    sqlite_conn_2 = _FakeConnection(dialect_name="sqlite")
    assert _capture_explain_plan(sqlite_conn_2, "insert into t values (1)", (), 5) == []

    failing_conn = _FakeConnection(dialect_name="sqlite", fail=True)
    assert _capture_explain_plan(failing_conn, "select 1", (), 5) == []

    ok_conn = _FakeConnection(dialect_name="sqlite")
    plan = _capture_explain_plan(ok_conn, "select 1", (), 5)
    assert plan == ["0, 0, 0, SCAN items"]
    assert ok_conn.info["_silk_explain_active"] is False
    assert ok_conn.info["_silk_explain_count"] == 1


def test_reports_dashboard_collapses_n_plus_one_timeline_rows() -> None:
    report = ProfileReport(
        method="GET",
        path="/items",
        status_code=200,
        duration_ms=30,
        sql_queries=[
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 1}",
                duration_ms=3,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_n_plus_one=True,
            ),
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 2}",
                duration_ms=4,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_n_plus_one=True,
            ),
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 3}",
                duration_ms=5,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_n_plus_one=True,
            ),
        ],
    )
    html_payload = render_reports_dashboard(
        [report],
        report,
        "/_silk/reports",
        "/_silk/reports/clear",
    )

    assert html_payload.count("timeline-row is-nplus1") == 1
    assert "n+1 x3" in html_payload
    assert "3 unique param sets" in html_payload
    assert "4.00 each · 12.00 total" in html_payload


def test_reports_dashboard_collapses_duplicate_timeline_rows() -> None:
    report = ProfileReport(
        method="GET",
        path="/items",
        status_code=200,
        duration_ms=30,
        sql_queries=[
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 1}",
                duration_ms=2,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_duplicate=True,
            ),
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 1}",
                duration_ms=4,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_duplicate=True,
            ),
            SQLQueryRecord(
                statement="SELECT * FROM items WHERE id = :id",
                params="{'id': 1}",
                duration_ms=5,
                rowcount=1,
                normalized_statement="select * from items where id = ?",
                is_duplicate=True,
            ),
        ],
    )
    html_payload = render_reports_dashboard(
        [report],
        report,
        "/_silk/reports",
        "/_silk/reports/clear",
    )

    assert html_payload.count("timeline-row is-duplicate") == 1
    assert "duplicate x3" in html_payload
    assert "3.67 each · 11.00 total" in html_payload


def test_after_cursor_execute_returns_when_capture_not_started() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    _after_cursor_execute(
        conn=conn,
        cursor=_FakeCursor(),
        statement="select 1",
        parameters=(),
        context=object(),
        executemany=False,
    )


def test_sql_param_masking_masks_sensitive_mapping_keys_by_default() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    collector, token = start_sql_capture()
    try:
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select :password, :token, :email",
            parameters={"password": "p@ss", "token": "abc", "email": "u@example.com"},
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select :password, :token, :email",
            parameters={"password": "p@ss", "token": "abc", "email": "u@example.com"},
            context=object(),
            executemany=False,
        )
    finally:
        stop_sql_capture(token)

    assert len(collector) == 1
    assert "'password': '***'" in collector[0].params
    assert "'token': '***'" in collector[0].params
    assert "'email': 'u@example.com'" in collector[0].params


def test_sql_param_masking_can_expose_raw_params_when_enabled() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    collector, token = start_sql_capture(
        SQLCaptureOptions(
            expose_raw_params=True,
            redacted_param_keys=("password", "token"),
        )
    )
    try:
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select :password, :token",
            parameters={"password": "p@ss", "token": "abc"},
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select :password, :token",
            parameters={"password": "p@ss", "token": "abc"},
            context=object(),
            executemany=False,
        )
    finally:
        stop_sql_capture(token)

    assert len(collector) == 1
    assert "'password': 'p@ss'" in collector[0].params
    assert "'token': 'abc'" in collector[0].params


def test_params_signature_is_stable_for_mapping_key_order() -> None:
    assert _params_signature({"a": 1, "b": 2}) == _params_signature({"b": 2, "a": 1})


def test_sql_capture_truncates_statement_and_params_with_flags() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    collector, token = start_sql_capture(
        SQLCaptureOptions(
            max_sql_length=24,
            max_params_length=20,
        )
    )
    try:
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="SELECT very_long_column_name FROM items WHERE id = :id",
            parameters={"id": "12345678901234567890"},
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="SELECT very_long_column_name FROM items WHERE id = :id",
            parameters={"id": "12345678901234567890"},
            context=object(),
            executemany=False,
        )
    finally:
        stop_sql_capture(token)

    assert len(collector) == 1
    assert collector[0].sql_truncated is True
    assert collector[0].params_truncated is True
    assert len(collector[0].statement) == 24
    assert len(collector[0].params) == 20


def test_sql_capture_respects_max_queries_per_request() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    collector, token = start_sql_capture(
        SQLCaptureOptions(
            max_queries_per_request=1,
        )
    )
    try:
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select 1",
            parameters=(),
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select 1",
            parameters=(),
            context=object(),
            executemany=False,
        )
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select 2",
            parameters=(),
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select 2",
            parameters=(),
            context=object(),
            executemany=False,
        )
    finally:
        stop_sql_capture(token)

    assert len(collector) == 1
    assert collector[0].statement == "select 1"


def test_handle_error_pops_stale_timing_frame() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    conn.info["_silk_query_timings"] = [("select 1", 1.0), ("select bad", 2.0)]

    _handle_error(_FakeExceptionContext(connection=conn))

    assert conn.info["_silk_query_timings"] == [("select 1", 1.0)]


def test_handle_error_prevents_next_query_from_using_failed_query_timing() -> None:
    conn = _FakeConnection(dialect_name="sqlite")
    collector, token = start_sql_capture()
    try:
        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select failed",
            parameters=(),
            context=object(),
            executemany=False,
        )
        _handle_error(_FakeExceptionContext(connection=conn))

        _before_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select ok",
            parameters=(),
            context=object(),
            executemany=False,
        )
        _after_cursor_execute(
            conn=conn,
            cursor=_FakeCursor(),
            statement="select ok",
            parameters=(),
            context=object(),
            executemany=False,
        )
    finally:
        stop_sql_capture(token)

    assert len(collector) == 1
    assert collector[0].statement == "select ok"


def test_reports_dashboard_respects_ui_config() -> None:
    report = ProfileReport(
        method="GET",
        path="/favicon.ico",
        status_code=404,
        duration_ms=12,
        sql_queries=[
            SQLQueryRecord(
                statement="SELECT very_long_column_name FROM some_table WHERE id = 1 "
                "AND another_column = 'value' AND a_third_column = 'value'",
                params="{}",
                duration_ms=1,
                rowcount=1,
            )
        ],
    )
    payload = render_reports_dashboard(
        reports=[report],
        selected_report=report,
        detail_base_path="/_silk/reports",
        clear_path="/_silk/reports/clear",
        dashboard_ui=DashboardUIConfig(
            default_requests_collapsed=True,
            default_pyinstrument_expanded=True,
            sql_preview_max_length=20,
            dim_favicon_requests=False,
            show_column_tooltips=False,
        ),
    )

    assert "$default_requests_collapsed" not in payload
    assert "$default_pyinstrument_expanded" not in payload
    assert "title=\"Execution sequence index within this request.\"" not in payload
    assert "report-item active is-noise" not in payload
    assert "sql-detail" in payload
    assert "sql-preview" in payload
