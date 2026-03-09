"""Public API for fastapi-silk-profiler."""

from .config import DashboardUIConfig, ProfilerConfig
from .endpoints import register_profiler_routes
from .middleware import SilkProfilerMiddleware
from .models import ProfileReport, QueryAnalysisSummary, SQLQueryRecord
from .query_analysis import QueryAnalysisConfig
from .setup import setup_silk_profiler
from .store import InMemoryReportStore, ReportStore, SQLiteReportStore

__all__ = [
    "InMemoryReportStore",
    "ProfileReport",
    "ProfilerConfig",
    "DashboardUIConfig",
    "QueryAnalysisConfig",
    "QueryAnalysisSummary",
    "ReportStore",
    "SQLQueryRecord",
    "SilkProfilerMiddleware",
    "SQLiteReportStore",
    "register_profiler_routes",
    "setup_silk_profiler",
]
