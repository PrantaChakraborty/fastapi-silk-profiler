# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog, and this project uses Semantic Versioning.

## [Unreleased]

### Added
- SQLite-backed profile storage via `SQLiteReportStore`.
- Dashboard endpoint `/_silk/reports` for browsing requests and SQL timing details.
- Per-report endpoint `/_silk/reports/{report_id}` and clear endpoint `POST /_silk/reports/clear`.

### Changed
- `setup_silk_profiler` now supports `sqlite_db_path`.
- Profiler auto-excludes dashboard endpoints from profiling to avoid self-profiling noise.

### Fixed
- Example/dev setup now includes `uvicorn` as a development dependency.

## [0.1.0] - 2026-03-06

### Added
- Initial FastAPI request profiling middleware.
- pyinstrument integration for per-request text and HTML reports.
- SQLAlchemy query capture with statement, params, duration, and rowcount.
- In-memory report storage with bounded retention.
- Latest-report endpoint with `json`, `text`, `html`, and `pyinstrument_html` formats.

---

## Release Entry Template

Copy this template for the next release:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- 

### Changed
- 

### Fixed
- 
```
