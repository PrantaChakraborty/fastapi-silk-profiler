# Releasing fastapi-silk-profiler

This document defines the exact release sequence for maintainers.

## Prerequisites

- Python 3.11+
- `uv` installed
- PyPI + TestPyPI access (trusted publishing environments preferred)
- Clean working tree

## 1. Prepare release branch state

1. Ensure version and changelog are ready.
2. Update `pyproject.toml` version (`MAJOR.MINOR.PATCH`).
3. Update `CHANGELOG.md` under a new release heading with date.

## 2. Run quality gates locally

```bash
uv venv
uv sync --all-extras --dev
uv run ruff check .
uv run mypy src
uv run pytest
uv build
uv run twine check dist/*
```

Do not continue if any command fails.

## 3. Validate package upload on TestPyPI first

```bash
uv run twine upload --repository testpypi dist/*
```

Optional install check:

```bash
uv pip install --index-url https://test.pypi.org/simple/ fastapi-silk-profiler
```

## 4. Publish to PyPI

```bash
uv run twine upload dist/*
```

## 5. Tag and push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The GitHub release workflow will:

1. Re-run quality checks.
2. Publish to TestPyPI.
3. Publish to PyPI for stable tags (`v*` without suffix).

## 6. Post-release checks

1. Verify package page on PyPI.
2. Verify install from PyPI in a fresh environment.
3. Move changelog template entries back under `Unreleased`.
