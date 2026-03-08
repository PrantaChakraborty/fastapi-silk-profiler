# AGENTS.md

## 1. Project Scope
- This repository contains a reusable FastAPI profiling package.
- The package is a PyPI-distributed library, not app-specific product code.
- Contributions must improve shared library behavior, API quality, reliability, docs, or release automation.

## 2. Repository Structure Rules
- `src/fastapi_silk_profiler/`: library source code only.
- `tests/`: unit, integration, and regression tests.
- `examples/`: runnable usage examples that reflect supported APIs.
- `docs/`: user and maintainer documentation.
- `.github/workflows/`: CI/CD workflows only.
- `pyproject.toml`: single source for package/build/tooling configuration.
- Keep new files in the correct top-level area; do not scatter code across ad hoc paths.

## 3. Environment & Commands (uv)
- Create/sync environment:
  - `uv venv`
  - `uv sync --all-extras --dev`
- Run tests:
  - `uv run pytest`
- Lint:
  - `uv run ruff check .`
- Typecheck:
  - `uv run mypy src`
- Build:
  - `uv build`
- Twine check:
  - `uv run twine check dist/*`

## 4. Coding Standards
- Target Python `>=3.11`.
- Use full type hints for all production code.
- Public functions/classes must include Google-style docstrings.
- Prefer small, focused functions and clear module boundaries.
- Avoid duplication; refactor shared logic into reusable internals.
- Maintain backward compatibility for the public API. Any intentional break must be explicit, documented, and versioned appropriately.

## 5. Testing Standards
- `pytest` coverage is required for all code changes.
- Every behavior change must include new or updated tests.
- Coverage target for touched modules is `>=95%`.
- Include middleware and SQL capture tests whenever those paths are affected.
- Fixes without tests are incomplete unless testing is impossible and justified in the PR notes.

## 6. Packaging & Release Standards
- Package metadata must follow PEP 621 in `pyproject.toml`.
- Use semantic versioning (`MAJOR.MINOR.PATCH`).
- Update changelog entries for user-visible changes before release.
- Release flow:
  1. Build artifacts.
  2. Publish/validate on TestPyPI first.
  3. Promote the same version to PyPI after validation.

## 7. CI Standards
- CI must enforce and pass all of the following before merge/release:
  - lint
  - typecheck
  - tests
  - build
  - `twine check`
- Failing checks block merges.

## 8. Security & Safety
- Never commit secrets, tokens, credentials, or private keys.
- Keep safe defaults: profiling must remain disabled unless explicitly enabled by configuration.
- Do not run destructive git commands (for example `reset --hard`, force-push, history rewrites) without explicit user/maintainer request.

## 9. Agent Workflow Rules
- Provide a short plan before major refactors.
- Implement changes first, then verify with the relevant commands.
- Report exactly what commands were run and their outcomes.
- Do not rewrite unrelated files or introduce opportunistic churn.
- Do not silently break the public API; call out impact and migration steps when needed.

## 10. Documentation Standards
- Keep README quickstart and configuration documentation up to date with current behavior.
- Update `examples/` whenever API surface or usage patterns change.
- Documentation changes are required for user-facing behavior or config changes.
