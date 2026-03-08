"""Configuration model for fastapi-silk-profiler."""

from __future__ import annotations

from dataclasses import dataclass, field

from .query_analysis import QueryAnalysisConfig


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
    """

    enabled: bool = False
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(
        default_factory=lambda: ["/docs", "/openapi.json", "/redoc", "/.well-known"]
    )
    store_size: int = 100
    capture_sql: bool = True
    query_analysis: QueryAnalysisConfig = field(default_factory=QueryAnalysisConfig)

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
