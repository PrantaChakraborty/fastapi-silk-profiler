"""Integration tests for fastapi-silk-profiler."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fastapi_silk_profiler import (
    InMemoryReportStore,
    ProfilerConfig,
    QueryAnalysisConfig,
    ReportStore,
    SQLiteReportStore,
    setup_silk_profiler,
)
from fastapi_silk_profiler.models import ProfileReport


def create_test_app(config: ProfilerConfig, store: ReportStore) -> FastAPI:
    """Create app fixture with profiling enabled/disabled by config."""
    app = FastAPI()
    setup_silk_profiler(app, config=config, store=store)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/skip")
    def skip() -> dict[str, str]:
        return {"status": "skip"}

    @app.get("/sql")
    def sql() -> dict[str, int]:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        return {"ok": 1}

    @app.get("/sql-analysis")
    def sql_analysis() -> dict[str, int]:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("select :value as value"), {"value": 1})
            conn.execute(text("select :value as value"), {"value": 1})
            conn.execute(text("select :value as value"), {"value": 2})
            conn.execute(text("select :value as value"), {"value": 3})
        engine.dispose()
        return {"ok": 1}

    return app


def test_middleware_disabled() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=False), store)
    client = TestClient(app)

    response = client.get("/ping")

    assert response.status_code == 200
    assert store.latest() is None


def test_middleware_enabled_creates_report() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    response = client.get("/ping")

    assert response.status_code == 200
    report = store.latest()
    assert report is not None
    assert report.path == "/ping"
    assert report.method == "GET"
    assert report.duration_ms >= 0


def test_path_exclusions() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(
        ProfilerConfig(enabled=True, exclude_paths=["/skip"], capture_sql=False),
        store,
    )
    client = TestClient(app)

    response = client.get("/skip")

    assert response.status_code == 200
    assert store.latest() is None


def test_sql_capture_records_queries() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=True), store)
    client = TestClient(app)

    response = client.get("/sql")

    assert response.status_code == 200
    report = store.latest()
    assert report is not None
    assert len(report.sql_queries) >= 1
    query = report.sql_queries[0]
    assert "select 1" in query.statement.lower()
    assert isinstance(query.params, str)
    assert query.duration_ms >= 0


def test_query_analysis_marks_slow_duplicate_and_n_plus_one() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(
        ProfilerConfig(
            enabled=True,
            capture_sql=True,
            query_analysis=QueryAnalysisConfig(
                enabled=True,
                slow_query_threshold_ms=0.0,
                duplicate_min_occurrences=2,
                n_plus_one_min_occurrences=3,
                capture_explain=False,
            ),
        ),
        store,
    )
    client = TestClient(app)

    response = client.get("/sql-analysis")

    assert response.status_code == 200
    report = store.latest()
    assert report is not None
    assert report.query_analysis.slow_query_count >= 4
    assert report.query_analysis.duplicate_query_count >= 2
    assert report.query_analysis.n_plus_one_query_count >= 4

    payload = client.get("/_silk/latest?format=json").json()
    assert payload["query_analysis"]["slow_query_count"] >= 4
    assert payload["query_analysis"]["duplicate_query_count"] >= 2
    assert payload["query_analysis"]["n_plus_one_query_count"] >= 4
    assert any(query["is_duplicate"] for query in payload["sql_queries"])
    assert any(query["is_n_plus_one"] for query in payload["sql_queries"])


def test_query_analysis_can_capture_sqlite_explain_plans() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(
        ProfilerConfig(
            enabled=True,
            capture_sql=True,
            query_analysis=QueryAnalysisConfig(
                enabled=True,
                capture_explain=True,
                explain_max_statements_per_request=5,
            ),
        ),
        store,
    )
    client = TestClient(app)

    response = client.get("/sql")

    assert response.status_code == 200
    report = store.latest()
    assert report is not None
    assert any(query.explain_plan for query in report.sql_queries)


def test_report_store_retention() -> None:
    store = InMemoryReportStore(max_size=2)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    client.get("/ping")
    client.get("/ping")
    client.get("/ping")

    assert len(store.list()) == 2


def test_latest_endpoint_formats() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    client.get("/ping")

    json_response = client.get("/_silk/latest?format=json")
    text_response = client.get("/_silk/latest?format=text")
    html_response = client.get("/_silk/latest?format=html")
    pyinstrument_response = client.get("/_silk/latest?format=pyinstrument_html")

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()["path"] == "/ping"

    assert text_response.status_code == 200
    assert text_response.headers["content-type"].startswith("text/plain")
    assert "Request: GET /ping" in text_response.text

    assert html_response.status_code == 200
    assert html_response.headers["content-type"].startswith("text/html")
    assert "fastapi-silk-profiler" in html_response.text

    assert pyinstrument_response.status_code == 200
    assert pyinstrument_response.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in pyinstrument_response.text


def test_latest_endpoint_returns_404_when_empty() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=False), store)
    client = TestClient(app)

    response = client.get("/_silk/latest?format=json")

    assert response.status_code == 404
    assert response.json()["detail"] == "No profiling report available"


def test_reports_dashboard_lists_and_selects_details() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=True), store)
    client = TestClient(app)

    client.get("/ping")
    client.get("/sql")
    latest = store.latest()
    assert latest is not None

    dashboard = client.get("/_silk/reports")
    selected = client.get(f"/_silk/reports?report_id={latest.id}")

    assert dashboard.status_code == 200
    assert "Captured Requests" in dashboard.text
    assert "Clear All Logs" in dashboard.text
    assert "Request Details" in dashboard.text

    assert selected.status_code == 200
    assert "SQL Timeline" in selected.text
    assert "Step" in selected.text
    assert "Time (ms)" in selected.text


def test_reports_dashboard_handles_missing_selected_report() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    client.get("/ping")
    response = client.get("/_silk/reports?report_id=missing-report-id")

    assert response.status_code == 200
    assert "Select a request to inspect details." in response.text


def test_reports_clear_endpoint_removes_all_data() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    client.get("/ping")
    assert store.latest() is not None

    clear_response = client.post("/_silk/reports/clear")
    latest_response = client.get("/_silk/latest?format=json")

    assert clear_response.status_code == 200
    assert clear_response.json() == {"ok": True}
    assert store.latest() is None
    assert latest_response.status_code == 404


def test_report_detail_endpoint_by_id() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    client.get("/ping")
    report = store.latest()
    assert report is not None

    detail = client.get(f"/_silk/reports/{report.id}?format=json")

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == report.id
    assert payload["path"] == "/ping"

    text_detail = client.get(f"/_silk/reports/{report.id}?format=text")
    html_detail = client.get(f"/_silk/reports/{report.id}?format=html")
    pyinstrument_detail = client.get(f"/_silk/reports/{report.id}?format=pyinstrument_html")

    assert text_detail.status_code == 200
    assert text_detail.headers["content-type"].startswith("text/plain")
    assert "Request: GET /ping" in text_detail.text

    assert html_detail.status_code == 200
    assert html_detail.headers["content-type"].startswith("text/html")
    assert "fastapi-silk-profiler" in html_detail.text

    assert pyinstrument_detail.status_code == 200
    assert pyinstrument_detail.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in pyinstrument_detail.text


def test_report_detail_endpoint_missing_id_returns_404() -> None:
    store = InMemoryReportStore(max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=False), store)
    client = TestClient(app)

    response = client.get("/_silk/reports/missing-id?format=json")

    assert response.status_code == 404
    assert response.json()["detail"] == "Profile report not found"


def test_sqlite_store_persists_reports_between_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "silk_profiles.db"
    store_a = SQLiteReportStore(db_path=str(db_path), max_size=10)
    app = create_test_app(ProfilerConfig(enabled=True, capture_sql=True), store_a)
    client = TestClient(app)

    client.get("/sql")
    latest = store_a.latest()
    assert latest is not None
    assert len(latest.sql_queries) >= 1

    store_b = SQLiteReportStore(db_path=str(db_path), max_size=10)
    restored = store_b.latest()
    assert restored is not None
    assert restored.id == latest.id
    assert restored.path == "/sql"
    assert restored.query_analysis.total_db_time_ms >= 0
    assert len(store_b) == 1

    store_a.clear()
    assert len(store_a) == 0
    assert store_a.latest() is None
    assert store_b.get(latest.id) is None

    store_a.close()
    store_b.close()


def test_sqlite_store_rejects_invalid_max_size(tmp_path: Path) -> None:
    db_path = tmp_path / "silk_profiles.db"

    try:
        SQLiteReportStore(db_path=str(db_path), max_size=0)
    except ValueError as exc:
        assert "max_size must be greater than 0" in str(exc)
    else:
        raise AssertionError("Expected ValueError for max_size=0")


def test_setup_silk_profiler_uses_sqlite_path(tmp_path: Path) -> None:
    db_path = tmp_path / "setup_store.db"
    app = FastAPI()

    store = setup_silk_profiler(
        app,
        config=ProfilerConfig(enabled=True, capture_sql=False),
        sqlite_db_path=str(db_path),
    )

    assert isinstance(store, SQLiteReportStore)
    store.close()


def test_setup_silk_profiler_prefers_explicit_store_over_sqlite_path(tmp_path: Path) -> None:
    db_path = tmp_path / "ignored.db"
    app = FastAPI()
    explicit_store = InMemoryReportStore(max_size=10)

    store = setup_silk_profiler(
        app,
        config=ProfilerConfig(enabled=True, capture_sql=False),
        store=explicit_store,
        sqlite_db_path=str(db_path),
    )

    assert store is explicit_store


def test_setup_silk_profiler_without_endpoint_registration() -> None:
    app = FastAPI()
    store = setup_silk_profiler(
        app,
        config=ProfilerConfig(enabled=True, capture_sql=False),
        register_endpoint=False,
    )

    assert isinstance(store, InMemoryReportStore)
    paths = {route.path for route in app.routes}
    assert "/_silk/latest" not in paths


def test_setup_enforces_profiler_and_wellknown_exclusions_with_custom_list() -> None:
    app = FastAPI()
    config = ProfilerConfig(enabled=True, exclude_paths=["/custom"])
    setup_silk_profiler(app, config=config)

    assert "/custom" in config.exclude_paths
    assert "/.well-known" in config.exclude_paths
    assert "/_silk" in config.exclude_paths
    assert "/_silk/latest" in config.exclude_paths
    assert "/_silk/reports" in config.exclude_paths


def test_inmemory_store_get_and_clear() -> None:
    store = InMemoryReportStore(max_size=3)
    report = ProfileReport(method="GET", path="/x", status_code=200, duration_ms=1.2)
    store.add(report)

    assert store.get(report.id) is report
    assert store.get("missing") is None
    assert len(store) == 1

    store.clear()
    assert len(store) == 0
