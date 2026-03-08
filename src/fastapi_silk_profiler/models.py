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


@dataclass(slots=True)
class ProfileReport:
    """Represents one profiled HTTP request."""

    method: str
    path: str
    status_code: int
    duration_ms: float
    sql_queries: list[SQLQueryRecord] = field(default_factory=list)
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
