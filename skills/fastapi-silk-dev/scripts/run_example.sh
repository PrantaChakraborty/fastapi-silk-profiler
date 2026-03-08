#!/usr/bin/env bash
set -euo pipefail

uv run uvicorn examples.basic_app.main:app --reload
