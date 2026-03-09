"""Query analysis utilities for captured SQL records."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import QueryAnalysisSummary, SQLQueryRecord

_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
_NUMERIC_LITERAL_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class QueryAnalysisConfig:
    """Configuration for SQL query analysis."""

    enabled: bool = True
    slow_query_threshold_ms: float = 100.0
    critical_query_threshold_ms: float | None = None
    duplicate_min_occurrences: int = 2
    n_plus_one_min_occurrences: int = 3
    capture_explain: bool = False
    explain_max_statements_per_request: int = 20


def normalize_sql(statement: str) -> str:
    """Normalize SQL statement for grouping.

    Args:
        statement: Raw SQL statement text.

    Returns:
        str: Normalized statement suitable for grouping.
    """
    lowered = statement.strip().lower()
    without_strings = _STRING_LITERAL_RE.sub("?", lowered)
    without_numbers = _NUMERIC_LITERAL_RE.sub("?", without_strings)
    return _WHITESPACE_RE.sub(" ", without_numbers).strip()


def analyze_queries(
    queries: list[SQLQueryRecord],
    request_duration_ms: float,
    config: QueryAnalysisConfig,
) -> QueryAnalysisSummary:
    """Annotate queries and return request-level analysis summary.

    Args:
        queries: Captured SQL query records for one request.
        request_duration_ms: Total request duration.
        config: Query analysis configuration.

    Returns:
        QueryAnalysisSummary: Aggregated analysis metrics.
    """
    total_db_time_ms = sum(query.duration_ms for query in queries)
    db_time_ratio = 0.0 if request_duration_ms <= 0 else total_db_time_ms / request_duration_ms
    summary = QueryAnalysisSummary(total_db_time_ms=total_db_time_ms, db_time_ratio=db_time_ratio)
    if not config.enabled or not queries:
        return summary

    critical_threshold = (
        config.critical_query_threshold_ms
        if config.critical_query_threshold_ms is not None
        else config.slow_query_threshold_ms * 5
    )
    for query in queries:
        normalized = normalize_sql(query.statement)
        query.normalized_statement = normalized
        query.is_slow = query.duration_ms >= config.slow_query_threshold_ms
        query.is_critical = query.duration_ms >= critical_threshold

    same_signature_counter = Counter(
        (
            q.normalized_statement,
            q.params_signature if q.params_signature else q.params,
        )
        for q in queries
    )
    duplicate_groups = {
        key
        for key, count in same_signature_counter.items()
        if count >= config.duplicate_min_occurrences
    }
    if duplicate_groups:
        for query in queries:
            dedupe_signature = query.params_signature if query.params_signature else query.params
            if (query.normalized_statement, dedupe_signature) in duplicate_groups:
                query.is_duplicate = True

    normalized_to_query_indexes: dict[str, list[int]] = defaultdict(list)
    normalized_to_params: dict[str, set[str]] = defaultdict(set)
    for index, query in enumerate(queries):
        normalized_to_query_indexes[query.normalized_statement].append(index)
        signature = query.params_signature if query.params_signature else query.params
        normalized_to_params[query.normalized_statement].add(signature)

    n_plus_one_groups: set[str] = set()
    for normalized, indexes in normalized_to_query_indexes.items():
        if len(indexes) < config.n_plus_one_min_occurrences:
            continue
        if len(normalized_to_params[normalized]) <= 1:
            continue
        n_plus_one_groups.add(normalized)
        for index in indexes:
            queries[index].is_n_plus_one = True

    summary.slow_query_count = sum(1 for query in queries if query.is_slow)
    summary.critical_query_count = sum(1 for query in queries if query.is_critical)
    summary.duplicate_query_count = sum(1 for query in queries if query.is_duplicate)
    summary.n_plus_one_query_count = sum(1 for query in queries if query.is_n_plus_one)
    summary.duplicate_query_groups = len(duplicate_groups)
    summary.n_plus_one_groups = len(n_plus_one_groups)
    return summary
