# fastapi-silk-profiler

Reusable FastAPI profiling middleware package with pyinstrument traces and SQLAlchemy query capture.

## Install

```bash
uv add fastapi-silk-profiler
```

## Quickstart

```python
from fastapi import FastAPI

from fastapi_silk_profiler import (
    DashboardUIConfig,
    ProfilerConfig,
    QueryAnalysisConfig,
    setup_silk_profiler,
)

app = FastAPI()
setup_silk_profiler(
    app,
    config=ProfilerConfig(
        enabled=True,
        capture_sql=True,
        query_analysis=QueryAnalysisConfig(
            enabled=True,
            slow_query_threshold_ms=100.0,
            duplicate_min_occurrences=2,
            n_plus_one_min_occurrences=3,
            capture_explain=False,  # set True to collect SQLite EXPLAIN QUERY PLAN
        ),
        dashboard_ui=DashboardUIConfig(
            default_requests_collapsed=False,
            default_pyinstrument_expanded=False,
            sql_preview_max_length=120,
            dim_favicon_requests=True,
            show_column_tooltips=True,
        ),
        exclude_paths=["/docs", "/openapi.json", "/redoc", "/_silk/latest"],
    ),
    profile_path_prefix="/_silk",  # optional override; default is "/_silk"
    sqlite_db_path="./silk_profiles.db",  # optional: persist reports to SQLite
)


@app.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}
```

Generate some traffic, then view the latest report:

- JSON: `/_silk/latest?format=json`
- Text: `/_silk/latest?format=text`
- Dashboard HTML: `/_silk/latest?format=html`
- Raw pyinstrument HTML: `/_silk/latest?format=pyinstrument_html`

You can mount profiler routes under any prefix with `profile_path_prefix`, for example
`profile_path_prefix="/debug-profiler"` exposes:

- `/debug-profiler`
- `/debug-profiler/latest`
- `/debug-profiler/reports`
- `/debug-profiler/reports/{report_id}`
- `POST /debug-profiler/reports/clear`

Browse all captured requests in a dashboard:

- Base dashboard: `/_silk`
- Reports dashboard: `/_silk/reports`
- Per-report API: `/_silk/reports/{report_id}?format=json`
- Clear logs API (used by dashboard button): `POST /_silk/reports/clear`

Template files (independent from Python logic):

- `src/fastapi_silk_profiler/templates/latest_dashboard.html`
- `src/fastapi_silk_profiler/templates/reports_dashboard.html`

## Configuration

`ProfilerConfig` fields:

- `enabled: bool` (default `False`)
- `include_paths: list[str]`
- `exclude_paths: list[str]`
- `store_size: int`
- `capture_sql: bool`
- `sql_capture: SQLCaptureConfig`
  - `max_queries_per_request: int` (default `1000`)
  - `max_sql_length: int` (default `5000`)
  - `max_params_length: int` (default `500`)
  - `capture_callsite: bool` (default `False`)
  - `capture_callsite_stack: bool` (default `True`, when callsite capture is enabled)
  - `capture_callsite_context: bool` (default `False`)
  - `callsite_context_max_lines: int` (default `60`)
- `sql_privacy: SQLPrivacyConfig`
  - `expose_raw_params: bool` (default `False`)
  - `redacted_param_keys: list[str]` (default includes `password`, `token`, `secret`, etc.)
- `profile_path_prefix: str` (argument to `setup_silk_profiler`; default `"/_silk"`)
- `query_analysis: QueryAnalysisConfig`
  - `enabled: bool`
  - `normalization_mode: Literal["regex", "sqlparse"]` (default `"regex"`)
  - `slow_query_threshold_ms: float`
  - `critical_query_threshold_ms: float | None` (`None` = `5x` slow threshold)
  - `duplicate_min_occurrences: int`
  - `n_plus_one_min_occurrences: int`
  - `capture_explain: bool` (SQLite support currently)
  - `explain_max_statements_per_request: int`
- `dashboard_ui: DashboardUIConfig`
  - `default_requests_collapsed: bool`
  - `default_pyinstrument_expanded: bool`
  - `sql_preview_max_length: int`
  - `dim_favicon_requests: bool`
  - `show_column_tooltips: bool`

Implementation status and phased roadmap:

- `docs/implementation-roadmap.md`

## Local Development

```bash
uv venv
uv sync --all-extras --dev
uv run ruff check .
uv run mypy src
uv run pytest
uv build
uv run twine check dist/*
```

## Example App

Run example app:

```bash
uvicorn examples.basic_app.main:app --reload
```

The example app includes CRUD + workload routes so you can generate profiling data without another project:

- `POST /seed`
- `GET /items`
- `POST /items`
- `PUT /items/{item_id}`
- `DELETE /items/{item_id}`
- `GET /workload`
- `GET /analysis-demo` (generates slow/duplicate/N+1 SQL patterns)

Then inspect:

- `/_silk/reports`

## Skills

Local reusable workflow skill:

- `skills/fastapi-silk-dev/SKILL.md`

Quick commands:

```bash
bash skills/fastapi-silk-dev/scripts/bootstrap.sh
bash skills/fastapi-silk-dev/scripts/quality.sh
bash skills/fastapi-silk-dev/scripts/run_example.sh
bash skills/fastapi-silk-dev/scripts/demo_db_flow.sh
```
