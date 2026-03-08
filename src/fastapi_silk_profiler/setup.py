"""Application integration helpers."""

from __future__ import annotations

from fastapi import FastAPI

from .config import ProfilerConfig
from .endpoints import register_latest_report_endpoint
from .middleware import SilkProfilerMiddleware
from .store import InMemoryReportStore, ReportStore, SQLiteReportStore


def setup_silk_profiler(
    app: FastAPI,
    config: ProfilerConfig | None = None,
    store: ReportStore | None = None,
    endpoint_path: str = "/_silk/latest",
    register_endpoint: bool = True,
    sqlite_db_path: str | None = None,
) -> ReportStore:
    """Attach middleware and optional debug endpoint to a FastAPI app.

    Args:
        app: FastAPI app instance.
        config: Optional profiler config.
        store: Optional report store.
        endpoint_path: Path to register the latest-report endpoint.
        register_endpoint: Whether to register the debug endpoint.
        sqlite_db_path: Optional SQLite DB path for persisted profiling logs.

    Returns:
        ReportStore: The active report store.
    """
    active_config = config if config is not None else ProfilerConfig()
    if store is not None:
        active_store = store
    elif sqlite_db_path is not None:
        active_store = SQLiteReportStore(
            db_path=sqlite_db_path,
            max_size=active_config.store_size,
        )
    else:
        active_store = InMemoryReportStore(max_size=active_config.store_size)

    if register_endpoint:
        base_prefix = endpoint_path.rsplit("/", maxsplit=1)[0] or "/"
        endpoint_exclusions = ["/.well-known", endpoint_path, f"{base_prefix}/reports"]
        if base_prefix != "/":
            endpoint_exclusions.append(base_prefix)
        for excluded_path in endpoint_exclusions:
            if excluded_path not in active_config.exclude_paths:
                active_config.exclude_paths.append(excluded_path)
        register_latest_report_endpoint(
            app,
            active_store,
            path=endpoint_path,
            config=active_config,
        )
    app.add_middleware(SilkProfilerMiddleware, config=active_config, store=active_store)
    return active_store
