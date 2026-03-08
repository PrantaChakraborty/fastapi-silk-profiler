# fastapi-silk-dev

## Purpose

This skill standardizes local development and validation workflows for the `fastapi-silk-profiler` package.

Use this skill when you want to:

- bootstrap the dev environment,
- run all quality gates,
- run the CRUD example app,
- generate profiling data quickly for dashboard testing.

## Location

- Skill root: `skills/fastapi-silk-dev`
- Scripts: `skills/fastapi-silk-dev/scripts`

## Commands

### 1) Bootstrap environment

```bash
bash skills/fastapi-silk-dev/scripts/bootstrap.sh
```

What it does:

- creates/uses `.venv` (`uv venv`)
- syncs deps with dev extras (`uv sync --all-extras --dev`)

### 2) Run quality checks

```bash
bash skills/fastapi-silk-dev/scripts/quality.sh
```

What it runs:

- `uv run ruff check .`
- `uv run mypy src`
- `uv run pytest`
- `uv build`
- `uv run twine check dist/*`

### 3) Run example app (CRUD + profiler)

```bash
bash skills/fastapi-silk-dev/scripts/run_example.sh
```

This starts:

- `uvicorn examples.basic_app.main:app --reload`

Then open:

- `http://127.0.0.1:8000/_silk/reports`

### 4) Seed and generate DB activity for profiling

```bash
bash skills/fastapi-silk-dev/scripts/demo_db_flow.sh
```

This script:

- seeds sample rows,
- runs workload route multiple times,
- creates/updates/deletes example items.

## Notes

- The profiler dashboard and `/.well-known` paths are auto-excluded from captured request logs.
- SQLite files used by example:
  - `example_app.db` (CRUD data)
  - `silk_profiles.db` (profiling logs)
