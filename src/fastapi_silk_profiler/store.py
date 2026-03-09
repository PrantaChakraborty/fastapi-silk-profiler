"""Report storage implementations."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict
from threading import Lock
from typing import Protocol

from .models import ProfileReport, QueryAnalysisSummary, SQLQueryRecord


def _sql_rows_to_records(rows: Sequence[sqlite3.Row]) -> list[SQLQueryRecord]:
    """Convert SQL query rows to model records.

    Args:
        rows: SQL rows tied to a report.

    Returns:
        list[SQLQueryRecord]: Query records in execution order.
    """
    return [
        SQLQueryRecord(
            statement=str(row["statement"]),
            params=str(row["params"]),
            duration_ms=float(row["duration_ms"]),
            rowcount=int(row["rowcount"]) if row["rowcount"] is not None else None,
            params_signature=str(row["params_signature"] or ""),
            normalized_statement=str(row["normalized_statement"] or ""),
            is_slow=bool(row["is_slow"]),
            is_critical=bool(row["is_critical"]),
            is_duplicate=bool(row["is_duplicate"]),
            is_n_plus_one=bool(row["is_n_plus_one"]),
            sql_truncated=bool(row["sql_truncated"]),
            params_truncated=bool(row["params_truncated"]),
            explain_plan=json.loads(str(row["explain_plan"] or "[]")),
        )
        for row in rows
    ]


class ReportStore(Protocol):
    """Storage interface used by middleware and endpoints."""

    def add(self, report: ProfileReport) -> None:
        """Persist one report."""

    def latest(self) -> ProfileReport | None:
        """Return the most recent report."""

    def list(self) -> list[ProfileReport]:
        """Return all reports."""

    def get(self, report_id: str) -> ProfileReport | None:
        """Return one report by id."""

    def clear(self) -> None:
        """Delete all stored reports."""


class InMemoryReportStore:
    """Bounded in-memory storage for profile reports."""

    def __init__(self, max_size: int = 100) -> None:
        """Initialize store.

        Args:
            max_size: Maximum number of reports to retain.
        """
        if max_size <= 0:
            raise ValueError("max_size must be greater than 0")
        self._reports: deque[ProfileReport] = deque(maxlen=max_size)

    def add(self, report: ProfileReport) -> None:
        """Add a report to the store.

        Args:
            report: Profile report instance.
        """
        self._reports.append(report)

    def latest(self) -> ProfileReport | None:
        """Return the most recent report.

        Returns:
            ProfileReport | None: Latest report if available.
        """
        return self._reports[-1] if self._reports else None

    def list(self) -> list[ProfileReport]:
        """Return reports ordered by insertion.

        Returns:
            list[ProfileReport]: Stored reports.
        """
        return list(self._reports)

    def get(self, report_id: str) -> ProfileReport | None:
        """Return one report by id.

        Args:
            report_id: Report identifier.

        Returns:
            ProfileReport | None: Matching report if available.
        """
        for report in self._reports:
            if report.id == report_id:
                return report
        return None

    def clear(self) -> None:
        """Remove all reports from memory."""
        self._reports.clear()

    def __len__(self) -> int:
        """Return number of stored reports.

        Returns:
            int: Number of reports.
        """
        return len(self._reports)


class SQLiteReportStore:
    """SQLite-backed report storage with bounded retention."""

    def __init__(self, db_path: str, max_size: int = 100) -> None:
        """Initialize SQLite storage.

        Args:
            db_path: Path to SQLite database file.
            max_size: Maximum number of reports to retain.
        """
        if max_size <= 0:
            raise ValueError("max_size must be greater than 0")
        self._max_size = max_size
        self._lock = Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    query_analysis_json TEXT NOT NULL DEFAULT '{}',
                    pyinstrument_text TEXT NOT NULL,
                    pyinstrument_html TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sql_queries (
                    report_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    statement TEXT NOT NULL,
                    params TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    rowcount INTEGER,
                    params_signature TEXT NOT NULL DEFAULT '',
                    normalized_statement TEXT NOT NULL DEFAULT '',
                    is_slow INTEGER NOT NULL DEFAULT 0,
                    is_critical INTEGER NOT NULL DEFAULT 0,
                    is_duplicate INTEGER NOT NULL DEFAULT 0,
                    is_n_plus_one INTEGER NOT NULL DEFAULT 0,
                    sql_truncated INTEGER NOT NULL DEFAULT 0,
                    params_truncated INTEGER NOT NULL DEFAULT 0,
                    explain_plan TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sql_queries_report_id ON sql_queries(report_id)"
            )
            self._ensure_column(
                table="reports",
                column="query_analysis_json",
                sql_type="TEXT",
                default_sql="'{}'",
            )
            self._ensure_column(
                table="sql_queries",
                column="params_signature",
                sql_type="TEXT",
                default_sql="''",
            )
            self._ensure_column(
                table="sql_queries",
                column="normalized_statement",
                sql_type="TEXT",
                default_sql="''",
            )
            self._ensure_column(
                table="sql_queries",
                column="is_slow",
                sql_type="INTEGER",
                default_sql="0",
            )
            self._ensure_column(
                table="sql_queries",
                column="is_duplicate",
                sql_type="INTEGER",
                default_sql="0",
            )
            self._ensure_column(
                table="sql_queries",
                column="is_critical",
                sql_type="INTEGER",
                default_sql="0",
            )
            self._ensure_column(
                table="sql_queries",
                column="is_n_plus_one",
                sql_type="INTEGER",
                default_sql="0",
            )
            self._ensure_column(
                table="sql_queries",
                column="explain_plan",
                sql_type="TEXT",
                default_sql="'[]'",
            )
            self._ensure_column(
                table="sql_queries",
                column="sql_truncated",
                sql_type="INTEGER",
                default_sql="0",
            )
            self._ensure_column(
                table="sql_queries",
                column="params_truncated",
                sql_type="INTEGER",
                default_sql="0",
            )

    def add(self, report: ProfileReport) -> None:
        """Persist one report.

        Args:
            report: Profile report instance.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO reports (
                    id, created_at, method, path, status_code, duration_ms,
                    query_analysis_json, pyinstrument_text, pyinstrument_html
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.created_at,
                    report.method,
                    report.path,
                    report.status_code,
                    report.duration_ms,
                    json.dumps(asdict(report.query_analysis)),
                    report.pyinstrument_text,
                    report.pyinstrument_html,
                ),
            )
            self._conn.executemany(
                """
                INSERT INTO sql_queries (
                    report_id, position, statement, params, duration_ms, rowcount,
                    params_signature, normalized_statement, is_slow, is_critical,
                    is_duplicate, is_n_plus_one, sql_truncated, params_truncated, explain_plan
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report.id,
                        index,
                        query.statement,
                        query.params,
                        query.duration_ms,
                        query.rowcount,
                        query.params_signature,
                        query.normalized_statement,
                        int(query.is_slow),
                        int(query.is_critical),
                        int(query.is_duplicate),
                        int(query.is_n_plus_one),
                        int(query.sql_truncated),
                        int(query.params_truncated),
                        json.dumps(query.explain_plan),
                    )
                    for index, query in enumerate(report.sql_queries)
                ],
            )
            self._trim_excess()

    def latest(self) -> ProfileReport | None:
        """Return the most recent report.

        Returns:
            ProfileReport | None: Latest report if available.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, created_at, method, path, status_code, duration_ms,
                       query_analysis_json, pyinstrument_text, pyinstrument_html
                FROM reports
                ORDER BY rowid DESC
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_report(row) if row is not None else None

    def list(self) -> list[ProfileReport]:
        """Return reports ordered by insertion.

        Returns:
            list[ProfileReport]: Stored reports from oldest to newest.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, created_at, method, path, status_code, duration_ms,
                       query_analysis_json, pyinstrument_text, pyinstrument_html
                FROM reports
                ORDER BY rowid ASC
                """
            ).fetchall()
            return [self._row_to_report(row) for row in rows]

    def get(self, report_id: str) -> ProfileReport | None:
        """Return one report by id.

        Args:
            report_id: Report identifier.

        Returns:
            ProfileReport | None: Matching report if available.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, created_at, method, path, status_code, duration_ms,
                       query_analysis_json, pyinstrument_text, pyinstrument_html
                FROM reports
                WHERE id = ?
                """,
                (report_id,),
            ).fetchone()
            return self._row_to_report(row) if row is not None else None

    def clear(self) -> None:
        """Delete all reports and SQL records."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM reports")

    def __len__(self) -> int:
        """Return number of stored reports.

        Returns:
            int: Number of reports.
        """
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()
            if row is None:
                return 0
            return int(row["count"])

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        """Best-effort cleanup for tests and short-lived processes."""
        try:
            self.close()
        except Exception:
            pass

    def _trim_excess(self) -> None:
        """Trim oldest reports beyond max size."""
        self._conn.execute(
            """
            DELETE FROM reports
            WHERE id IN (
                SELECT id
                FROM reports
                ORDER BY rowid DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self._max_size,),
        )

    def _row_to_report(self, row: sqlite3.Row) -> ProfileReport:
        """Build a ProfileReport from report row.

        Args:
            row: Report database row.

        Returns:
            ProfileReport: Reconstructed report.
        """
        sql_rows = self._conn.execute(
            """
            SELECT statement, params, duration_ms, rowcount, params_signature
                   ,normalized_statement, is_slow, is_critical
                   ,is_duplicate, is_n_plus_one, sql_truncated, params_truncated, explain_plan
            FROM sql_queries
            WHERE report_id = ?
            ORDER BY position ASC
            """,
            (row["id"],),
        ).fetchall()
        raw_summary = str(row["query_analysis_json"] or "{}")
        summary_json = json.loads(raw_summary)
        return ProfileReport(
            id=str(row["id"]),
            created_at=str(row["created_at"]),
            method=str(row["method"]),
            path=str(row["path"]),
            status_code=int(row["status_code"]),
            duration_ms=float(row["duration_ms"]),
            query_analysis=QueryAnalysisSummary(**summary_json),
            pyinstrument_text=str(row["pyinstrument_text"]),
            pyinstrument_html=str(row["pyinstrument_html"]),
            sql_queries=_sql_rows_to_records(sql_rows),
        )

    def _ensure_column(self, table: str, column: str, sql_type: str, default_sql: str) -> None:
        """Add column when missing to support in-place schema upgrades."""
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column in existing:
            return
        self._conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type} NOT NULL DEFAULT {default_sql}"
        )
