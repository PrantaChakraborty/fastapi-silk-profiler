"""FastAPI middleware integration for request profiling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter

from pyinstrument import Profiler
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .config import ProfilerConfig
from .models import ProfileReport, SQLQueryRecord
from .query_analysis import analyze_queries
from .sql_capture import (
    SQLCaptureOptions,
    ensure_sqlalchemy_hooks,
    start_sql_capture,
    stop_sql_capture,
)
from .store import ReportStore


class SilkProfilerMiddleware(BaseHTTPMiddleware):
    """Request middleware that captures pyinstrument and SQL profiling data."""

    def __init__(self, app: ASGIApp, config: ProfilerConfig, store: ReportStore) -> None:
        """Initialize middleware.

        Args:
            app: ASGI app.
            config: Profiler config.
            store: Report store.
        """
        super().__init__(app)
        self._config = config
        self._store = store
        if self._config.capture_sql:
            ensure_sqlalchemy_hooks()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Handle one incoming request.

        Args:
            request: Incoming request.
            call_next: Next middleware handler.

        Returns:
            Response: HTTP response.
        """
        if not self._config.should_profile(request.url.path):
            return await call_next(request)

        profiler = Profiler(async_mode="enabled")
        sql_queries: list[SQLQueryRecord] = []
        sql_token = None
        if self._config.capture_sql:
            sql_queries, sql_token = start_sql_capture(
                SQLCaptureOptions(
                    capture_explain=self._config.query_analysis.capture_explain,
                    explain_max_statements_per_request=(
                        self._config.query_analysis.explain_max_statements_per_request
                    ),
                )
            )

        started = perf_counter()
        response: Response | None = None
        try:
            profiler.start()
            response = await call_next(request)
            return response
        finally:
            profiler.stop()
            if sql_token is not None:
                stop_sql_capture(sql_token)
            duration_ms = (perf_counter() - started) * 1000
            query_analysis = analyze_queries(
                queries=sql_queries,
                request_duration_ms=duration_ms,
                config=self._config.query_analysis,
            )
            report = ProfileReport(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code if response is not None else 500,
                duration_ms=duration_ms,
                sql_queries=sql_queries,
                query_analysis=query_analysis,
                pyinstrument_text=profiler.output_text(unicode=True, color=False),
                pyinstrument_html=profiler.output_html(),
            )
            self._store.add(report)
