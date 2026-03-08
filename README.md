# fastapi-silk-profiler

Reusable FastAPI profiling middleware package with pyinstrument traces and SQLAlchemy query capture.

## Install

```bash
uv add fastapi-silk-profiler
```

## Quickstart

```python
from fastapi import FastAPI

from fastapi_silk_profiler import ProfilerConfig, setup_silk_profiler

app = FastAPI()
setup_silk_profiler(
    app,
    config=ProfilerConfig(
        enabled=True,
        capture_sql=True,
        exclude_paths=["/docs", "/openapi.json", "/redoc", "/_silk/latest"],
    ),
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

Browse all captured requests in a dashboard:

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
uv run uvicorn examples.basic_app.main:app --reload
```

The example app includes CRUD + workload routes so you can generate profiling data without another project:

- `POST /seed`
- `GET /items`
- `POST /items`
- `PUT /items/{item_id}`
- `DELETE /items/{item_id}`
- `GET /workload`

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
