"""Report rendering utilities."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jinja2 import Environment, PackageLoader, Template, select_autoescape

from .config import DashboardUIConfig
from .models import ProfileReport


@cache
def _template_env() -> Environment:
    """Build cached Jinja environment for package templates."""
    return Environment(
        loader=PackageLoader("fastapi_silk_profiler", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
    )


@cache
def _load_template(template_name: str) -> Template:
    """Load one HTML template from packaged resources."""
    return _template_env().get_template(template_name)


def render_json(report: ProfileReport) -> dict[str, object]:
    """Render report data as JSON-ready dictionary.

    Args:
        report: Profile report.

    Returns:
        dict[str, object]: JSON-ready payload.
    """
    return report.to_dict()


def render_text(report: ProfileReport) -> str:
    """Render report as readable plain text.

    Args:
        report: Profile report.

    Returns:
        str: Plain text report.
    """
    lines = [
        f"Profile ID: {report.id}",
        f"Time: {report.created_at}",
        f"Request: {report.method} {report.path}",
        f"Status: {report.status_code}",
        f"Duration: {report.duration_ms:.2f} ms",
        f"SQL Queries: {len(report.sql_queries)}",
        f"Total DB Time: {report.query_analysis.total_db_time_ms:.2f} ms",
        f"DB Time Ratio: {report.query_analysis.db_time_ratio:.2%}",
        f"Slow Queries: {report.query_analysis.slow_query_count}",
        f"Critical Queries: {report.query_analysis.critical_query_count}",
        f"Duplicate Queries: {report.query_analysis.duplicate_query_count}",
        f"N+1 Queries: {report.query_analysis.n_plus_one_query_count}",
    ]
    for index, query in enumerate(report.sql_queries, start=1):
        flags = []
        if query.is_critical:
            flags.append("critical")
        if query.is_slow:
            flags.append("slow")
        if query.is_duplicate:
            flags.append("duplicate")
        if query.is_n_plus_one:
            flags.append("n+1")
        flag_text = ",".join(flags) if flags else "-"
        lines.append(
            f"  [{index}] {query.duration_ms:.2f} ms "
            f"| rowcount={query.rowcount} | flags={flag_text}"
        )
        if query.callsite:
            lines.append(f"      Callsite: {query.callsite}")
        if query.callsite_stack:
            lines.append("      Stack:")
            for stack_line in query.callsite_stack:
                lines.append(f"        {stack_line}")
        if query.callsite_code:
            lines.append(f"      Source: {query.callsite_code}")
        lines.append(f"      SQL: {query.statement}")
        lines.append(f"      Params: {query.params}")
        if query.explain_plan:
            lines.append(f"      EXPLAIN: {' | '.join(query.explain_plan)}")
    lines.append("")
    lines.append("Pyinstrument:")
    lines.append(report.pyinstrument_text)
    return "\n".join(lines)


def render_pyinstrument_html(report: ProfileReport) -> str:
    """Return the raw pyinstrument HTML output.

    Args:
        report: Profile report.

    Returns:
        str: Raw pyinstrument HTML.
    """
    return report.pyinstrument_html


def render_html_dashboard(report: ProfileReport) -> str:
    """Render latest report dashboard HTML.

    Args:
        report: Profile report.

    Returns:
        str: Styled dashboard HTML.
    """
    queries_json = json.dumps(
        [
            {
                "statement": query.statement,
                "params": query.params,
                "duration_ms": query.duration_ms,
                "rowcount": query.rowcount,
                "callsite": query.callsite,
                "callsite_code": query.callsite_code,
                "callsite_stack": query.callsite_stack,
                "callsite_context": query.callsite_context,
                "callsite_highlight_line": query.callsite_highlight_line,
                "params_signature": query.params_signature,
                "normalized_statement": query.normalized_statement,
                "is_slow": query.is_slow,
                "is_critical": query.is_critical,
                "is_duplicate": query.is_duplicate,
                "is_n_plus_one": query.is_n_plus_one,
                "sql_truncated": query.sql_truncated,
                "params_truncated": query.params_truncated,
                "explain_plan": query.explain_plan,
            }
            for query in report.sql_queries
        ],
        indent=2,
    )
    metrics = [
        {"label": "Method", "value": report.method},
        {"label": "Path", "value": report.path},
        {"label": "Status", "value": str(report.status_code)},
        {"label": "Duration", "value": f"{report.duration_ms:.2f} ms"},
        {"label": "SQL Queries", "value": str(len(report.sql_queries))},
    ]
    return _load_template("latest_dashboard.html").render(
        metrics=metrics,
        queries_json=queries_json,
        pyinstrument_text=report.pyinstrument_text,
    )


def _short_sql(statement: str, max_len: int = 140) -> str:
    """Return a compact SQL preview for table display."""
    compact = " ".join(statement.split())
    return compact if len(compact) <= max_len else f"{compact[:max_len - 1]}..."


@dataclass(slots=True)
class _NPlusOneTimelineBucket:
    count: int = 0
    total_ms: float = 0.0
    sample_sql: str = ""
    params: set[str] = field(default_factory=set)
    explain_plan: list[str] = field(default_factory=list)
    callsites: set[str] = field(default_factory=set)
    callsite_code_by_origin: dict[str, str] = field(default_factory=dict)
    callsite_stack_by_origin: dict[str, list[str]] = field(default_factory=dict)
    callsite_context_by_origin: dict[str, list[str]] = field(default_factory=dict)
    callsite_highlight_by_origin: dict[str, int | None] = field(default_factory=dict)
    has_slow: bool = False
    has_critical: bool = False


@dataclass(slots=True)
class _DuplicateTimelineBucket:
    count: int = 0
    total_ms: float = 0.0
    sample_sql: str = ""
    params: str = ""
    explain_plan: list[str] = field(default_factory=list)
    callsites: set[str] = field(default_factory=set)
    callsite_code_by_origin: dict[str, str] = field(default_factory=dict)
    callsite_stack_by_origin: dict[str, list[str]] = field(default_factory=dict)
    callsite_context_by_origin: dict[str, list[str]] = field(default_factory=dict)
    callsite_highlight_by_origin: dict[str, int | None] = field(default_factory=dict)
    has_slow: bool = False
    has_critical: bool = False


def _build_query_rows(report: ProfileReport, ui: DashboardUIConfig) -> list[dict[str, Any]]:
    """Build SQL timeline rows for dashboard template."""
    n_plus_one_buckets: dict[str, _NPlusOneTimelineBucket] = defaultdict(_NPlusOneTimelineBucket)
    duplicate_buckets: dict[tuple[str, str], _DuplicateTimelineBucket] = defaultdict(
        _DuplicateTimelineBucket
    )

    for query in report.sql_queries:
        if query.is_n_plus_one:
            key = query.normalized_statement or query.statement
            bucket = n_plus_one_buckets[key]
            bucket.count += 1
            bucket.total_ms += query.duration_ms
            bucket.params.add(query.params)
            bucket.has_slow = bucket.has_slow or query.is_slow
            bucket.has_critical = bucket.has_critical or query.is_critical
            if not bucket.sample_sql:
                bucket.sample_sql = query.statement
            if not bucket.explain_plan and query.explain_plan:
                bucket.explain_plan = query.explain_plan
            if query.callsite:
                bucket.callsites.add(query.callsite)
                if query.callsite_code and query.callsite not in bucket.callsite_code_by_origin:
                    bucket.callsite_code_by_origin[query.callsite] = query.callsite_code
                if query.callsite_stack and query.callsite not in bucket.callsite_stack_by_origin:
                    bucket.callsite_stack_by_origin[query.callsite] = query.callsite_stack
                if (
                    query.callsite_context
                    and query.callsite not in bucket.callsite_context_by_origin
                ):
                    bucket.callsite_context_by_origin[query.callsite] = query.callsite_context
                    bucket.callsite_highlight_by_origin[query.callsite] = (
                        query.callsite_highlight_line
                    )
            continue
        if query.is_duplicate:
            dup_key = (query.normalized_statement or query.statement, query.params)
            dup_bucket = duplicate_buckets[dup_key]
            dup_bucket.count += 1
            dup_bucket.total_ms += query.duration_ms
            dup_bucket.has_slow = dup_bucket.has_slow or query.is_slow
            dup_bucket.has_critical = dup_bucket.has_critical or query.is_critical
            if not dup_bucket.sample_sql:
                dup_bucket.sample_sql = query.statement
                dup_bucket.params = query.params
            if not dup_bucket.explain_plan and query.explain_plan:
                dup_bucket.explain_plan = query.explain_plan
            if query.callsite:
                dup_bucket.callsites.add(query.callsite)
                if query.callsite_code and query.callsite not in dup_bucket.callsite_code_by_origin:
                    dup_bucket.callsite_code_by_origin[query.callsite] = query.callsite_code
                if (
                    query.callsite_stack
                    and query.callsite not in dup_bucket.callsite_stack_by_origin
                ):
                    dup_bucket.callsite_stack_by_origin[query.callsite] = query.callsite_stack
                if (
                    query.callsite_context
                    and query.callsite not in dup_bucket.callsite_context_by_origin
                ):
                    dup_bucket.callsite_context_by_origin[query.callsite] = query.callsite_context
                    dup_bucket.callsite_highlight_by_origin[query.callsite] = (
                        query.callsite_highlight_line
                    )

    rows: list[dict[str, Any]] = []
    emitted_n_plus_one_keys: set[str] = set()
    emitted_duplicate_keys: set[tuple[str, str]] = set()

    for index, query in enumerate(report.sql_queries, start=1):
        n_plus_one_key = query.normalized_statement or query.statement
        if query.is_n_plus_one:
            if n_plus_one_key in emitted_n_plus_one_keys:
                continue
            emitted_n_plus_one_keys.add(n_plus_one_key)
            bucket = n_plus_one_buckets[n_plus_one_key]
            avg_ms = bucket.total_ms / bucket.count if bucket.count else 0.0
            flags = [{"class_name": "badge-nplus1", "text": f"n+1 x{bucket.count}"}]
            if bucket.has_critical:
                flags.insert(0, {"class_name": "badge-critical", "text": "critical"})
            elif bucket.has_slow:
                flags.insert(0, {"class_name": "badge-slow", "text": "slow"})
            rows.append(
                {
                    "row_class": "timeline-row is-nplus1",
                    "step": str(index),
                    "time_value": bucket.total_ms,
                    "time": f"{avg_ms:.2f} each · {bucket.total_ms:.2f} total",
                    "time_label": f"{avg_ms:.2f} ms each · {bucket.total_ms:.2f} ms total",
                    "rowcount": "-",
                    "flags": flags,
                    "count_label": f"×{bucket.count}" if bucket.count > 1 else "",
                    "filter_tags": ["n+1"]
                    + (["critical"] if bucket.has_critical else [])
                    + (["slow"] if bucket.has_slow else []),
                    "sql_full": bucket.sample_sql,
                    "origin_blocks": (
                        [
                            {
                                "origin": callsite,
                                "code_line": bucket.callsite_code_by_origin.get(callsite, ""),
                                "stack_lines": bucket.callsite_stack_by_origin.get(callsite, []),
                                "context_lines": bucket.callsite_context_by_origin.get(
                                    callsite,
                                    [],
                                ),
                                "highlight_line": bucket.callsite_highlight_by_origin.get(callsite),
                            }
                            for callsite in sorted(bucket.callsites)[:3]
                        ]
                        + (
                            [
                                {
                                    "origin": f"... +{len(bucket.callsites) - 3} more origins",
                                    "code_line": "",
                                    "stack_lines": [],
                                    "context_lines": [],
                                    "highlight_line": None,
                                }
                            ]
                            if len(bucket.callsites) > 3
                            else []
                        )
                        if bucket.callsites
                        else [
                            {
                                "origin": "-",
                                "code_line": "",
                                "stack_lines": [],
                                "context_lines": [],
                                "highlight_line": None,
                            }
                        ]
                    ),
                    "params": f"{len(bucket.params)} unique param sets",
                    "explain": "<br>".join(bucket.explain_plan),
                }
            )
            continue

        if query.is_duplicate:
            duplicate_key = (query.normalized_statement or query.statement, query.params)
            if duplicate_key in emitted_duplicate_keys:
                continue
            emitted_duplicate_keys.add(duplicate_key)
            duplicate_bucket = duplicate_buckets[duplicate_key]
            avg_ms = (
                duplicate_bucket.total_ms / duplicate_bucket.count
                if duplicate_bucket.count
                else 0.0
            )
            duplicate_flags = [
                {
                    "class_name": "badge-duplicate",
                    "text": f"duplicate x{duplicate_bucket.count}",
                }
            ]
            if duplicate_bucket.has_critical:
                duplicate_flags.insert(0, {"class_name": "badge-critical", "text": "critical"})
            elif duplicate_bucket.has_slow:
                duplicate_flags.insert(0, {"class_name": "badge-slow", "text": "slow"})
            rows.append(
                {
                    "row_class": "timeline-row is-duplicate",
                    "step": str(index),
                    "time_value": duplicate_bucket.total_ms,
                    "time": f"{avg_ms:.2f} each · {duplicate_bucket.total_ms:.2f} total",
                    "time_label": (
                        f"{avg_ms:.2f} ms each · {duplicate_bucket.total_ms:.2f} ms total"
                    ),
                    "rowcount": "-",
                    "flags": duplicate_flags,
                    "count_label": (
                        f"×{duplicate_bucket.count}" if duplicate_bucket.count > 1 else ""
                    ),
                    "filter_tags": ["duplicate"]
                    + (["critical"] if duplicate_bucket.has_critical else [])
                    + (["slow"] if duplicate_bucket.has_slow else []),
                    "sql_full": duplicate_bucket.sample_sql,
                    "origin_blocks": (
                        [
                            {
                                "origin": callsite,
                                "code_line": duplicate_bucket.callsite_code_by_origin.get(
                                    callsite,
                                    "",
                                ),
                                "stack_lines": duplicate_bucket.callsite_stack_by_origin.get(
                                    callsite,
                                    [],
                                ),
                                "context_lines": duplicate_bucket.callsite_context_by_origin.get(
                                    callsite,
                                    [],
                                ),
                                "highlight_line": duplicate_bucket.callsite_highlight_by_origin.get(
                                    callsite
                                ),
                            }
                            for callsite in sorted(duplicate_bucket.callsites)[:3]
                        ]
                        + (
                            [
                                {
                                    "origin": (
                                        f"... +{len(duplicate_bucket.callsites) - 3} more origins"
                                    ),
                                    "code_line": "",
                                    "stack_lines": [],
                                    "context_lines": [],
                                    "highlight_line": None,
                                }
                            ]
                            if len(duplicate_bucket.callsites) > 3
                            else []
                        )
                        if duplicate_bucket.callsites
                        else [
                            {
                                "origin": "-",
                                "code_line": "",
                                "stack_lines": [],
                                "context_lines": [],
                                "highlight_line": None,
                            }
                        ]
                    ),
                    "params": duplicate_bucket.params,
                    "explain": "<br>".join(duplicate_bucket.explain_plan),
                }
            )
            continue

        row_flags: list[dict[str, str]] = []
        if query.is_critical:
            row_flags.append({"class_name": "badge-critical", "text": "critical"})
        if query.is_slow:
            row_flags.append({"class_name": "badge-slow", "text": "slow"})

        row_class = "timeline-row"
        if query.is_critical:
            row_class += " is-critical"
        elif query.is_slow:
            row_class += " is-slow"

        rows.append(
            {
                "row_class": row_class,
                "step": str(index),
                "time_value": query.duration_ms,
                "time": f"{query.duration_ms:.2f}",
                "time_label": f"{query.duration_ms:.2f} ms",
                "rowcount": "-" if query.rowcount is None else str(query.rowcount),
                "flags": row_flags,
                "count_label": "",
                "filter_tags": [
                    flag["text"]
                    for flag in row_flags
                    if flag["text"] in {"critical", "slow", "n+1", "duplicate"}
                ],
                "sql_full": query.statement,
                "origin_blocks": (
                    [
                        {
                            "origin": query.callsite,
                            "code_line": query.callsite_code,
                            "stack_lines": query.callsite_stack,
                            "context_lines": query.callsite_context,
                            "highlight_line": query.callsite_highlight_line,
                        }
                    ]
                    if query.callsite
                    else [
                        {
                            "origin": "-",
                            "code_line": "",
                            "stack_lines": [],
                            "context_lines": [],
                            "highlight_line": None,
                        }
                    ]
                ),
                "params": query.params,
                "explain": "<br>".join(query.explain_plan),
            }
        )

    return rows


def render_reports_dashboard(
    reports: list[ProfileReport],
    selected_report: ProfileReport | None,
    detail_base_path: str,
    clear_path: str,
    dashboard_ui: DashboardUIConfig | None = None,
) -> str:
    """Render list/detail dashboard for all captured reports.

    Args:
        reports: Available reports.
        selected_report: Currently selected report.
        detail_base_path: Base path used for detail links.
        clear_path: API path used to clear all reports.
        dashboard_ui: Optional UI behavior configuration.

    Returns:
        str: Full HTML dashboard.
    """
    ui = dashboard_ui if dashboard_ui is not None else DashboardUIConfig()
    selected_id = selected_report.id if selected_report is not None else ""

    report_items = [
        {
            "id": report.id,
            "method": report.method,
            "path": report.path,
            "status_code": report.status_code,
            "duration_ms": f"{report.duration_ms:.2f}",
            "created_at": report.created_at,
            "active": report.id == selected_id,
            "is_noise": ui.dim_favicon_requests and report.path == "/favicon.ico",
        }
        for report in reports
    ]

    details: dict[str, Any] | None = None
    if selected_report is not None:
        details = {
            "method": selected_report.method,
            "path": selected_report.path,
            "status_code": selected_report.status_code,
            "created_at": selected_report.created_at,
            "chips": [
                {
                    "class_name": "chip-critical",
                    "text": f"{selected_report.query_analysis.critical_query_count} critical",
                },
                {
                    "class_name": "chip-slow",
                    "text": f"{selected_report.query_analysis.slow_query_count} warnings",
                },
                {
                    "class_name": "chip-nplus1",
                    "text": f"{selected_report.query_analysis.n_plus_one_query_count} n+1",
                },
            ],
            "metrics": [
                {"label": "Total Time", "value": f"{selected_report.duration_ms:.2f} ms"},
                {
                    "label": "Total DB Time",
                    "value": f"{selected_report.query_analysis.total_db_time_ms:.2f} ms",
                },
                {
                    "label": "DB Time Ratio",
                    "value": f"{selected_report.query_analysis.db_time_ratio:.2%}",
                },
                {
                    "label": "Slow Queries",
                    "value": str(selected_report.query_analysis.slow_query_count),
                },
                {
                    "label": "Duplicate Queries",
                    "value": str(selected_report.query_analysis.duplicate_query_count),
                },
                {
                    "label": "N+1 Queries",
                    "value": str(selected_report.query_analysis.n_plus_one_query_count),
                },
            ],
            "query_rows": _build_query_rows(selected_report, ui),
            "pyinstrument_text": selected_report.pyinstrument_text,
        }

    timeline_headers = [
        {
            "label": "Step",
            "tooltip": "Execution sequence index within this request.",
        },
        {
            "label": "Time (ms)",
            "tooltip": "Execution time for this SQL statement in milliseconds.",
        },
        {
            "label": "Rows",
            "tooltip": "Row count reported by driver; -1 often means not provided.",
        },
        {
            "label": "Flags",
            "tooltip": "Detected analysis tags for this query.",
        },
        {
            "label": "SQL",
            "tooltip": "Captured SQL statement (click to expand when trimmed).",
        },
        {
            "label": "Origin",
            "tooltip": "Best-effort app callsite that triggered this query.",
        },
        {
            "label": "Context",
            "tooltip": "Captured params and EXPLAIN plan details.",
        },
    ]

    return _load_template("reports_dashboard.html").render(
        report_count=len(reports),
        report_items=report_items,
        detail_base_path=detail_base_path,
        details=details,
        timeline_headers=timeline_headers,
        show_column_tooltips=ui.show_column_tooltips,
        escaped_clear_path=clear_path,
        default_requests_collapsed="1" if ui.default_requests_collapsed else "0",
        default_pyinstrument_expanded="1" if ui.default_pyinstrument_expanded else "0",
    )
