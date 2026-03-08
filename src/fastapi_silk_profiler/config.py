"""Configuration model for fastapi-silk-profiler."""

from __future__ import annotations

from dataclasses import dataclass, field

from .query_analysis import QueryAnalysisConfig


@dataclass(slots=True)
class DashboardUIConfig:
    """Configuration for reports dashboard UI behavior.

    Attributes:
        default_requests_collapsed: Collapses request list on first load when True.
        default_pyinstrument_expanded: Expands pyinstrument panel on first load when True.
        sql_preview_max_length: Maximum SQL preview length before click-to-expand behavior.
        dim_favicon_requests: De-emphasize /favicon.ico request rows when True.
        show_column_tooltips: Show column help tooltips in tables when True.
    """

    default_requests_collapsed: bool = False
    default_pyinstrument_expanded: bool = False
    sql_preview_max_length: int = 120
    dim_favicon_requests: bool = True
    show_column_tooltips: bool = True


@dataclass(slots=True)
class ProfilerConfig:
    """Runtime configuration for the profiling middleware.

    Attributes:
        enabled: Enables profiling when True.
        include_paths: Optional list of path prefixes that are allowed.
        exclude_paths: Path prefixes that should never be profiled.
        store_size: Maximum number of reports to keep in memory.
        capture_sql: Enables SQLAlchemy query capture when True.
        query_analysis: SQL query analysis behavior.
        dashboard_ui: Reports dashboard UI behavior.
    """

    enabled: bool = False
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(
        default_factory=lambda: ["/docs", "/openapi.json", "/redoc", "/.well-known"]
    )
    store_size: int = 100
    capture_sql: bool = True
    query_analysis: QueryAnalysisConfig = field(default_factory=QueryAnalysisConfig)
    dashboard_ui: DashboardUIConfig = field(default_factory=DashboardUIConfig)

    def should_profile(self, path: str) -> bool:
        """Return True when a request path should be profiled.

        Args:
            path: Request path.

        Returns:
            bool: Whether profiling should run for this path.
        """
        if not self.enabled:
            return False
        if self.include_paths and not any(path.startswith(prefix) for prefix in self.include_paths):
            return False
        if any(path.startswith(prefix) for prefix in self.exclude_paths):
            return False
        return True
