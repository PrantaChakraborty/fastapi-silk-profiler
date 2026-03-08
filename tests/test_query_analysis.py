"""Unit tests for query analysis and related rendering/capture helpers."""

from __future__ import annotations

from dataclasses import replace

from fastapi_silk_profiler.config import DashboardUIConfig
from fastapi_silk_profiler.models import ProfileReport, SQLQueryRecord
from fastapi_silk_profiler.query_analysis import QueryAnalysisConfig, analyze_queries, normalize_sql
from fastapi_silk_profiler.renderers import render_reports_dashboard, render_text
from fastapi_silk_profiler.sql_capture import _after_cursor_execute, _capture_explain_plan


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
    assert "Top N+1 Query Offenders" in html_payload


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
    assert _capture_explain_plan(pg_conn, "select 1", (), 5) == []

    sqlite_conn_2 = _FakeConnection(dialect_name="sqlite")
    assert _capture_explain_plan(sqlite_conn_2, "insert into t values (1)", (), 5) == []

    failing_conn = _FakeConnection(dialect_name="sqlite", fail=True)
    assert _capture_explain_plan(failing_conn, "select 1", (), 5) == []

    ok_conn = _FakeConnection(dialect_name="sqlite")
    plan = _capture_explain_plan(ok_conn, "select 1", (), 5)
    assert plan == ["0, 0, 0, SCAN items"]
    assert ok_conn.info["_silk_explain_active"] is False
    assert ok_conn.info["_silk_explain_count"] == 1


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
