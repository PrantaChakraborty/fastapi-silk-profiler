#!/usr/bin/env bash
set -euo pipefail

uv run ruff check .
uv run mypy src
uv run pytest
uv build
uv run twine check dist/*

echo "All quality checks passed."
