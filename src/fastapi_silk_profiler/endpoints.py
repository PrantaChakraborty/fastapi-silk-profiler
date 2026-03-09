"""Debug endpoint helpers."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from .config import ProfilerConfig
from .renderers import (
    render_html_dashboard,
    render_json,
    render_pyinstrument_html,
    render_reports_dashboard,
    render_text,
)
from .store import ReportStore

ReportFormat = Literal["json", "text", "html", "pyinstrument_html"]


def register_profiler_routes(
    app: FastAPI,
    store: ReportStore,
    path: str = "/_silk/latest",
    config: ProfilerConfig | None = None,
) -> None:
    """Register all profiler HTTP routes (latest report + dashboard + actions).

    Args:
        app: FastAPI application.
        store: In-memory report store.
        path: Endpoint path.
        config: Optional profiler config for dashboard rendering settings.
    """

    @app.get(path)
    def latest_report(
        format: Annotated[ReportFormat, Query(description="Output format")] = "html",
    ) -> Response:
        """Return latest report in requested format.

        Args:
            format: Response format selector.

        Returns:
            Response: Rendered report payload.
        """
        report = store.latest()
        if report is None:
            raise HTTPException(status_code=404, detail="No profiling report available")

        if format == "json":
            return JSONResponse(render_json(report))
        if format == "text":
            return PlainTextResponse(render_text(report))
        if format == "html":
            return HTMLResponse(render_html_dashboard(report))
        return HTMLResponse(render_pyinstrument_html(report))

    base_prefix = path.rsplit("/", maxsplit=1)[0] or "/"
    reports_path = f"{base_prefix}/reports"
    clear_path = f"{reports_path}/clear"
    detail_path = f"{reports_path}" + "/{report_id}"

    def _render_reports_dashboard(selected_report_id: str | None = None) -> HTMLResponse:
        """Render list/detail profiling dashboard HTML."""
        reports = list(reversed(store.list()))
        selected = reports[0] if reports else None
        if selected_report_id is not None:
            selected = store.get(selected_report_id)
        return HTMLResponse(
            render_reports_dashboard(
                reports=reports,
                selected_report=selected,
                detail_base_path=reports_path,
                clear_path=clear_path,
                dashboard_ui=config.dashboard_ui if config is not None else None,
            )
        )

    @app.get(reports_path)
    def reports_dashboard(
        report_id: Annotated[str | None, Query(description="Selected report id")] = None,
    ) -> HTMLResponse:
        """Render list/detail profiling dashboard."""
        return _render_reports_dashboard(selected_report_id=report_id)

    if base_prefix != "/":

        @app.get(base_prefix)
        def reports_dashboard_base() -> HTMLResponse:
            """Render profiling dashboard at the profiler base URL."""
            return _render_reports_dashboard()

    @app.get(detail_path)
    def report_detail(
        report_id: str,
        format: Annotated[ReportFormat, Query(description="Output format")] = "html",
    ) -> Response:
        """Return one report by id in requested format."""
        report = store.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Profile report not found")
        if format == "json":
            return JSONResponse(render_json(report))
        if format == "text":
            return PlainTextResponse(render_text(report))
        if format == "html":
            return HTMLResponse(render_html_dashboard(report))
        return HTMLResponse(render_pyinstrument_html(report))

    @app.post(clear_path)
    def clear_reports() -> JSONResponse:
        """Clear all profiling reports."""
        store.clear()
        return JSONResponse({"ok": True})
