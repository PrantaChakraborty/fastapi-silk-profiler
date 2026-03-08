"""Report rendering utilities."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from string import Template

from .models import ProfileReport


@cache
def _load_template(template_name: str) -> Template:
    """Load one HTML template from packaged resources.

    Args:
        template_name: Template filename under templates/.

    Returns:
        Template: Compiled string template.
    """
    content = (
        files("fastapi_silk_profiler")
        .joinpath("templates")
        .joinpath(template_name)
        .read_text(encoding="utf-8")
    )
    return Template(content)


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
        f"Duplicate Queries: {report.query_analysis.duplicate_query_count}",
        f"N+1 Queries: {report.query_analysis.n_plus_one_query_count}",
    ]
    for index, query in enumerate(report.sql_queries, start=1):
        flags = []
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
    """Render a dark observability-style HTML dashboard.

    Args:
        report: Profile report.

    Returns:
        str: Styled dashboard HTML.
    """
    queries_json = html.escape(
        json.dumps(
            [
                {
                    "statement": query.statement,
                    "params": query.params,
                    "duration_ms": query.duration_ms,
                    "rowcount": query.rowcount,
                    "normalized_statement": query.normalized_statement,
                    "is_slow": query.is_slow,
                    "is_duplicate": query.is_duplicate,
                    "is_n_plus_one": query.is_n_plus_one,
                    "explain_plan": query.explain_plan,
                }
                for query in report.sql_queries
            ],
            indent=2,
        )
    )
    method_metric = (
        "<div class=\\\"metric\\\"><div class=\\\"label\\\">Method</div>"
        f"<div class=\\\"value\\\">{html.escape(report.method)}</div></div>"
    )
    path_metric = (
        "<div class=\\\"metric\\\"><div class=\\\"label\\\">Path</div>"
        f"<div class=\\\"value\\\">{html.escape(report.path)}</div></div>"
    )
    status_metric = (
        "<div class=\\\"metric\\\"><div class=\\\"label\\\">Status</div>"
        f"<div class=\\\"value\\\">{report.status_code}</div></div>"
    )
    duration_metric = (
        "<div class=\\\"metric\\\"><div class=\\\"label\\\">Duration</div>"
        f"<div class=\\\"value\\\">{report.duration_ms:.2f} ms</div></div>"
    )
    sql_count_metric = (
        "<div class=\\\"metric\\\"><div class=\\\"label\\\">SQL Queries</div>"
        f"<div class=\\\"value\\\">{len(report.sql_queries)}</div></div>"
    )
    return _load_template("latest_dashboard.html").substitute(
        method_metric=method_metric,
        path_metric=path_metric,
        status_metric=status_metric,
        duration_metric=duration_metric,
        sql_count_metric=sql_count_metric,
        queries_json=queries_json,
        pyinstrument_text=html.escape(report.pyinstrument_text),
    )


def _short_sql(statement: str, max_len: int = 140) -> str:
    """Return a compact SQL preview for table display."""
    compact = " ".join(statement.split())
    return compact if len(compact) <= max_len else f"{compact[:max_len - 1]}..."


@dataclass(slots=True)
class _QueryGroupBucket:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    sample_sql: str = ""


@dataclass(slots=True)
class _NPlusOneGroupBucket(_QueryGroupBucket):
    params: set[str] = field(default_factory=set)


def _render_group_card(
    title: str,
    columns: list[str],
    rows: list[list[str]],
    empty_message: str,
) -> str:
    """Render one query-analysis group card."""
    if not rows:
        return (
            f"<section class=\"card\"><h3>{html.escape(title)}</h3>"
            f"<div class=\"empty\">{html.escape(empty_message)}</div></section>"
        )
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows)
    return (
        f"<section class=\"card\"><h3>{html.escape(title)}</h3>"
        f"<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></section>"
    )


def _render_query_analysis_groups(report: ProfileReport) -> str:
    """Render grouped bottleneck analysis tables for one report."""
    slow_groups: dict[str, _QueryGroupBucket] = defaultdict(_QueryGroupBucket)
    duplicate_groups: dict[tuple[str, str], _QueryGroupBucket] = defaultdict(_QueryGroupBucket)
    n_plus_one_groups: dict[str, _NPlusOneGroupBucket] = defaultdict(_NPlusOneGroupBucket)

    for query in report.sql_queries:
        normalized_key = query.normalized_statement or query.statement
        if query.is_slow:
            bucket = slow_groups[normalized_key]
            bucket.count += 1
            bucket.total_ms += query.duration_ms
            bucket.max_ms = max(bucket.max_ms, query.duration_ms)
            if not bucket.sample_sql:
                bucket.sample_sql = query.statement
        if query.is_duplicate:
            bucket = duplicate_groups[(normalized_key, query.params)]
            bucket.count += 1
            bucket.total_ms += query.duration_ms
            bucket.max_ms = max(bucket.max_ms, query.duration_ms)
            if not bucket.sample_sql:
                bucket.sample_sql = query.statement
        if query.is_n_plus_one:
            bucket = n_plus_one_groups[normalized_key]
            bucket.count += 1
            bucket.total_ms += query.duration_ms
            bucket.max_ms = max(bucket.max_ms, query.duration_ms)
            bucket.params.add(query.params)
            if not bucket.sample_sql:
                bucket.sample_sql = query.statement

    slow_rows = [
        [
            str(bucket.count),
            f"{bucket.total_ms:.2f}",
            f"{bucket.max_ms:.2f}",
            _short_sql(bucket.sample_sql),
        ]
        for _, bucket in sorted(
            slow_groups.items(),
            key=lambda item: item[1].total_ms,
            reverse=True,
        )[:5]
    ]
    duplicate_rows = [
        [
            str(bucket.count),
            f"{bucket.total_ms:.2f}",
            f"{bucket.max_ms:.2f}",
            _short_sql(bucket.sample_sql),
        ]
        for _, bucket in sorted(
            duplicate_groups.items(),
            key=lambda item: item[1].total_ms,
            reverse=True,
        )[:5]
    ]
    n_plus_one_rows: list[list[str]] = []
    for _, bucket in sorted(
        n_plus_one_groups.items(),
        key=lambda item: item[1].total_ms,
        reverse=True,
    )[:5]:
        n_plus_one_rows.append(
            [
                str(bucket.count),
                str(len(bucket.params)),
                f"{bucket.total_ms:.2f}",
                f"{bucket.max_ms:.2f}",
                _short_sql(bucket.sample_sql),
            ]
        )

    return "".join(
        [
            _render_group_card(
                title="Top Slow Query Offenders",
                columns=["Calls", "Total ms", "Max ms", "SQL"],
                rows=slow_rows,
                empty_message="No slow queries flagged.",
            ),
            _render_group_card(
                title="Top Duplicate Query Offenders",
                columns=["Calls", "Total ms", "Max ms", "SQL"],
                rows=duplicate_rows,
                empty_message="No duplicate query groups flagged.",
            ),
            _render_group_card(
                title="Top N+1 Query Offenders",
                columns=["Calls", "Unique Params", "Total ms", "Max ms", "SQL"],
                rows=n_plus_one_rows,
                empty_message="No N+1 patterns flagged.",
            ),
        ]
    )


def render_reports_dashboard(
    reports: list[ProfileReport],
    selected_report: ProfileReport | None,
    detail_base_path: str,
    clear_path: str,
) -> str:
    """Render list/detail dashboard for all captured reports.

    Args:
        reports: Available reports.
        selected_report: Currently selected report.
        detail_base_path: Base path used for detail links.
        clear_path: API path used to clear all reports.

    Returns:
        str: Full HTML dashboard.
    """
    selected_id = selected_report.id if selected_report is not None else ""
    escaped_base_path = html.escape(detail_base_path)
    escaped_clear_path = html.escape(clear_path)
    list_items = []
    for report in reports:
        active_class = "active" if report.id == selected_id else ""
        escaped_id = html.escape(report.id)
        escaped_method = html.escape(report.method)
        escaped_path = html.escape(report.path)
        escaped_created_at = html.escape(report.created_at)
        list_items.append(
            f"<a class=\"report-item {active_class}\" "
            f"href=\"{escaped_base_path}?report_id={escaped_id}\">"
            f"<div class=\"request\">{escaped_method} {escaped_path}</div>"
            f"<div class=\"meta\">{report.status_code} · {report.duration_ms:.2f} ms"
            f" · {escaped_created_at}</div></a>"
        )
    report_list_html = (
        "".join(list_items)
        if list_items
        else "<div class=\"empty\">No profile reports captured yet.</div>"
    )

    if selected_report is None:
        details_html = "<div class=\"empty\">Select a request to inspect details.</div>"
    else:
        selected_method = html.escape(selected_report.method)
        selected_path = html.escape(selected_report.path)
        selected_created_at = html.escape(selected_report.created_at)
        query_rows = []
        for index, query in enumerate(selected_report.sql_queries, start=1):
            escaped_statement = html.escape(query.statement)
            escaped_params = html.escape(query.params)
            escaped_explain = "<br>".join(html.escape(line) for line in query.explain_plan)
            flags = []
            if query.is_slow:
                flags.append("slow")
            if query.is_duplicate:
                flags.append("duplicate")
            if query.is_n_plus_one:
                flags.append("n+1")
            flags_text = ", ".join(flags) if flags else "-"
            rowcount_value = "-" if query.rowcount is None else str(query.rowcount)
            query_rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{query.duration_ms:.2f}</td>"
                f"<td>{rowcount_value}</td>"
                f"<td>{flags_text}</td>"
                f"<td><code>{escaped_statement}</code></td>"
                f"<td><code>{escaped_params}</code></td>"
                f"<td><code>{escaped_explain or '-'}</code></td>"
                "</tr>"
            )
        queries_table = (
            (
                "<table><thead><tr><th>Step</th><th>Time (ms)</th><th>Rows</th>"
                "<th>Flags</th><th>SQL</th><th>Params</th><th>EXPLAIN</th>"
                "</tr></thead><tbody>{rows}</tbody></table>"
            ).format(rows="".join(query_rows))
            if query_rows
            else "<div class=\"empty\">No SQL queries captured for this request.</div>"
        )
        details_html = f"""
        <div class="summary-grid">
          <div class="metric"><span>Method</span><strong>{selected_method}</strong></div>
          <div class="metric"><span>Path</span><strong>{selected_path}</strong></div>
          <div class="metric"><span>Status</span>
            <strong>{selected_report.status_code}</strong></div>
          <div class="metric"><span>Total Time</span>
            <strong>{selected_report.duration_ms:.2f} ms</strong></div>
          <div class="metric"><span>SQL Count</span>
            <strong>{len(selected_report.sql_queries)}</strong></div>
          <div class="metric"><span>Total DB Time</span>
            <strong>{selected_report.query_analysis.total_db_time_ms:.2f} ms</strong></div>
          <div class="metric"><span>DB Time Ratio</span>
            <strong>{selected_report.query_analysis.db_time_ratio:.2%}</strong></div>
          <div class="metric"><span>Slow Queries</span>
            <strong>{selected_report.query_analysis.slow_query_count}</strong></div>
          <div class="metric"><span>Duplicate Queries</span>
            <strong>{selected_report.query_analysis.duplicate_query_count}</strong></div>
          <div class="metric"><span>N+1 Queries</span>
            <strong>{selected_report.query_analysis.n_plus_one_query_count}</strong></div>
          <div class="metric"><span>Captured At</span><strong>{selected_created_at}</strong></div>
        </div>
        {_render_query_analysis_groups(selected_report)}
        <section class="card">
          <h3>SQL Timeline</h3>
          {queries_table}
        </section>
        <section class="card">
          <h3>Pyinstrument (Text)</h3>
          <pre>{html.escape(selected_report.pyinstrument_text)}</pre>
        </section>
        """

    return _load_template("reports_dashboard.html").substitute(
        report_count=str(len(reports)),
        report_list_html=report_list_html,
        details_html=details_html,
        escaped_clear_path=escaped_clear_path,
    )
