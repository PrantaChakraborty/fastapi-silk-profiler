# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog, and this project uses Semantic Versioning.

## [Unreleased]

### Added
- SQLite-backed profile storage via `SQLiteReportStore`.
- Dashboard endpoint `/_silk/reports` for browsing requests and SQL timing details.
- Per-report endpoint `/_silk/reports/{report_id}` and clear endpoint `POST /_silk/reports/clear`.
- Query analysis engine with per-request DB summary metrics (`total_db_time_ms`, `db_time_ratio`).
- Slow/duplicate/N+1 SQL heuristics and per-query flags in JSON/text/dashboard views.
- Optional SQLite `EXPLAIN QUERY PLAN` capture with request-level cap.
- Configurable dashboard UI settings via `DashboardUIConfig` (request panel default state,
  pyinstrument default state, SQL preview length, favicon dimming, tooltip toggles).
- Configurable profiler URL prefix via `setup_silk_profiler(..., profile_path_prefix=...)`.
- SQL parameter privacy controls via `SQLPrivacyConfig` with default masking for
  sensitive keys and optional raw-param capture.
- SQL capture limits via `SQLCaptureConfig` (`max_queries_per_request`,
  `max_sql_length`, `max_params_length`) with per-query truncation flags.
- Stable parameter signatures for duplicate/N+1 grouping to avoid order-sensitive
  false negatives from stringified params.

### Changed
- `setup_silk_profiler` now supports `sqlite_db_path`.
- Profiler auto-excludes dashboard endpoints from profiling to avoid self-profiling noise.
- `ProfilerConfig` now supports `QueryAnalysisConfig` for SQL analysis tuning.
- Profiler base URL (for example `/_silk`) now renders the reports dashboard.

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
