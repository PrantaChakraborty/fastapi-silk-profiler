"""Data models for profiling reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class SQLQueryRecord:
    """Represents one captured SQL query."""

    statement: str
    params: str
    duration_ms: float
    rowcount: int | None
    normalized_statement: str = ""
    is_slow: bool = False
    is_critical: bool = False
    is_duplicate: bool = False
    is_n_plus_one: bool = False
    explain_plan: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueryAnalysisSummary:
    """Request-level SQL analysis summary."""

    total_db_time_ms: float = 0.0
    db_time_ratio: float = 0.0
    slow_query_count: int = 0
    critical_query_count: int = 0
    duplicate_query_count: int = 0
    duplicate_query_groups: int = 0
    n_plus_one_query_count: int = 0
    n_plus_one_groups: int = 0


@dataclass(slots=True)
class ProfileReport:
    """Represents one profiled HTTP request."""

    method: str
    path: str
    status_code: int
    duration_ms: float
    sql_queries: list[SQLQueryRecord] = field(default_factory=list)
    query_analysis: QueryAnalysisSummary = field(default_factory=QueryAnalysisSummary)
    pyinstrument_text: str = ""
    pyinstrument_html: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a JSON-serializable dictionary.

        Returns:
            dict[str, Any]: Report fields including nested SQL records.
        """
        return asdict(self)
