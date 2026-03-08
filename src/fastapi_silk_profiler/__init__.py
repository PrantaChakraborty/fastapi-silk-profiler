"""Public API for fastapi-silk-profiler."""

from .config import DashboardUIConfig, ProfilerConfig
from .endpoints import register_latest_report_endpoint
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
    "register_latest_report_endpoint",
    "setup_silk_profiler",
]
