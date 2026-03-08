#!/usr/bin/env bash
set -euo pipefail

uv venv
uv sync --all-extras --dev

echo "Environment ready."
