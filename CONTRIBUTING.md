# Contributing

## Local setup

```bash
uv venv
uv sync --all-extras --dev
```

## Development commands

- Lint: `uv run ruff check .`
- Typecheck: `uv run mypy src`
- Tests: `uv run pytest`
- Build: `uv build`
- Twine check: `uv run twine check dist/*`

## Contribution rules

- Keep changes focused and avoid unrelated file edits.
- Add or update tests for every behavior change.
- Maintain backward compatibility for public APIs unless explicitly versioned as a breaking change.
- Use full type hints and Google-style docstrings for public functions/classes.

## Pull requests

1. Run all local quality gates before opening the PR.
2. Update `README.md` and examples when API behavior changes.
3. Update `CHANGELOG.md` for user-visible changes.
