# Implementation Roadmap

This document tracks what is implemented now and what is planned next for `fastapi-silk-profiler`.

## Scope

Current product strategy is to prioritize **database profiling** first, then expand into request visibility depth, then async/concurrency diagnostics.

## Implemented Now

### Foundation

- FastAPI middleware with per-request profiling lifecycle.
- `pyinstrument` capture (text + HTML).
- SQLAlchemy event-based SQL capture.
- In-memory and SQLite report stores.
- Latest report endpoint and reports dashboard.

### Request Metadata (Current)

- Request method and path.
- Response status code.
- End-to-end duration in milliseconds.
- Request timestamp and unique report id.

### Database Profiling (Current)

- Query count per request.
- Raw SQL statement and parameters (stringified).
- Per-query execution time.
- Row count per query (where available).
- Per-request SQL timeline in dashboard.
- Persistent SQL history in SQLite mode.
- Request-level DB summary fields:
  - `total_db_time_ms`
  - `db_time_ratio`
- Slow query flagging with configurable threshold.
- Duplicate query detection (same normalized SQL + same params).
- N+1 heuristic (same normalized SQL with varying params).
- Optional SQLite `EXPLAIN QUERY PLAN` capture.

### Dashboard (Current)

- Captured request list.
- Click-through request details.
- SQL step timeline table.
- Pyinstrument text view.
- Clear logs action.

## In Progress / Next (DB-Focused)

1. Query grouping UI:
   - Slow queries section
   - Duplicate/N+1 warnings per request
2. Extended `EXPLAIN` support beyond SQLite.

## Future Phases

### Request Visibility Expansion

- Request/response size in bytes.
- Route pattern/handler identity.
- Query/path parameter display.
- Client IP, user-agent, and auth context fields.
- Environment tag support (`dev`, `staging`, `prod`).
- Optional middleware-layer timing breakdown.

### Async & Concurrency Profiling

- Active concurrent request count.
- Background task timing and exception capture.
- Connection pool wait time instrumentation.
- Event loop lag/blocking signal capture.
- Executor/threadpool usage metrics.

## Non-Goals (for now)

- Full distributed tracing backend replacement.
- Zero-overhead always-on production tracing.
- Automatic root-cause attribution for every async stall.

## Delivery Notes

- Backward compatibility is preserved for current API surface.
- New profiling fields will be added incrementally in report schema.
- High-overhead diagnostics should remain configurable and opt-in.
