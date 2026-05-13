"""SQLite-backed query planner for dismissed agent archive summaries."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parser import AgentQueryParseError, parse_agent_query
from .types import (
    AndExpr,
    DurationCompare,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)

_LIVE_ONLY_KEYS = frozenset({"hidden", "attention", "needs", "pinned", "tag"})


class ArchiveQueryError(Exception):
    """Raised when an archive query cannot be planned."""


@dataclass(frozen=True)
class ArchiveQueryResult:
    """Compact archive search result row."""

    agent_id: str
    raw_suffix: str
    bundle_path: str
    cl_name: str
    agent_name: str | None
    status: str
    start_time: str | None
    dismissed_at: str | None
    revived_at: str | None
    project_name: str | None
    model: str | None
    runtime: str | None
    llm_provider: str | None
    step_index: int | None
    step_name: str | None
    step_type: str | None
    retry_attempt: int
    is_workflow_child: bool


@dataclass(frozen=True)
class ArchiveQueryPage:
    """One paged archive query result set."""

    results: list[ArchiveQueryResult]
    next_cursor: int | None


def search_archive(
    root: Path,
    query: str,
    *,
    limit: int = 50,
    cursor: int | None = None,
) -> ArchiveQueryPage:
    """Search archive summaries without hydrating bundle JSON files."""

    where_sql, params = _compile_query_text(query)
    offset = max(0, cursor or 0)
    page_size = max(0, limit)
    sql = (
        "SELECT s.* FROM dismissed_bundle_summaries s "
        f"WHERE {where_sql} "
        "ORDER BY COALESCE(s.start_time, s.raw_suffix) DESC, "
        "s.filename ASC LIMIT ? OFFSET ?"
    )
    from ..dismissed_bundle_index import archive_index_connection, archive_index_exists

    if not archive_index_exists(root):
        return ArchiveQueryPage(results=[], next_cursor=None)

    try:
        with archive_index_connection(root) as conn:
            rows = conn.execute(sql, [*params, page_size + 1, offset]).fetchall()
    except sqlite3.Error as exc:
        raise ArchiveQueryError(str(exc)) from exc

    result_rows = rows[:page_size]
    next_cursor = offset + page_size if len(rows) > page_size else None
    return ArchiveQueryPage(
        results=[_result_from_row(row) for row in result_rows],
        next_cursor=next_cursor,
    )


def select_archive_results(
    root: Path,
    *,
    agent_id: str | None = None,
    name: str | None = None,
    suffix: str | None = None,
    limit: int = 50,
) -> list[ArchiveQueryResult]:
    """Select archive summary rows by exact stable identifiers."""

    selectors = {
        "agent_id": agent_id,
        "name": name,
        "suffix": suffix,
    }
    active = [(key, value) for key, value in selectors.items() if value]
    if len(active) != 1:
        raise ArchiveQueryError("Expected exactly one archive result selector")

    key, value = active[0]
    if key == "agent_id":
        clause = "(s.raw_suffix = ? OR s.filename = ? OR s.bundle_path = ?)"
        params = [value, value, value]
    elif key == "name":
        clause = "(s.agent_name = ? OR s.cl_name = ? OR s.meta_changespec = ?)"
        params = [value, value, value]
    else:
        clause = "s.raw_suffix = ?"
        params = [value]

    sql = (
        "SELECT s.* FROM dismissed_bundle_summaries s "
        f"WHERE {clause} "
        "ORDER BY COALESCE(s.start_time, s.raw_suffix) DESC, "
        "s.filename ASC LIMIT ?"
    )
    from ..dismissed_bundle_index import archive_index_connection, archive_index_exists

    if not archive_index_exists(root):
        return []

    try:
        with archive_index_connection(root) as conn:
            rows = conn.execute(sql, [*params, max(0, limit)]).fetchall()
    except sqlite3.Error as exc:
        raise ArchiveQueryError(str(exc)) from exc
    return [_result_from_row(row) for row in rows]


def _compile_query_text(query: str) -> tuple[str, list[Any]]:
    query = query.strip()
    if not query:
        return "1 = 1", []
    archive_only = _compile_archive_only_property(query)
    if archive_only is not None:
        return archive_only
    try:
        expr = parse_agent_query(query)
    except AgentQueryParseError as exc:
        raise ArchiveQueryError(str(exc)) from exc
    return _compile_expr(expr)


def _compile_archive_only_property(query: str) -> tuple[str, list[Any]] | None:
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(.*)", query)
    if match is None:
        return None
    key = match.group(1).lower()
    value = match.group(2).strip().strip('"')
    if key == "archived_before":
        return "COALESCE(s.start_time, s.raw_suffix) < ?", [value]
    if key == "archived_after":
        return "COALESCE(s.start_time, s.raw_suffix) >= ?", [value]
    if key == "runtime":
        return _like("s.llm_provider", value)
    if key == "retry_of":
        return _like("s.retry_of_timestamp", value)
    if key == "parent":
        return _like("s.parent_timestamp", value)
    if key == "step_type":
        return _like("s.agent_type", value)
    if key == "revived":
        return "1 = 0" if value == "true" else "1 = 1", []
    return None


def _compile_expr(expr: QueryExpr) -> tuple[str, list[Any]]:
    if isinstance(expr, AndExpr):
        return _join_expr("AND", expr.operands)
    if isinstance(expr, OrExpr):
        return _join_expr("OR", expr.operands)
    if isinstance(expr, NotExpr):
        clause, params = _compile_expr(expr.operand)
        return f"NOT ({clause})", params
    if isinstance(expr, StringMatch):
        return _compile_text_match(expr.value)
    if isinstance(expr, PropertyMatch):
        return _compile_property(expr)
    if isinstance(expr, DurationCompare):
        raise ArchiveQueryError(
            "Archive queries do not support age comparisons; use "
            "archived_before: or archived_after: instead"
        )
    raise TypeError(f"Unknown expression type: {type(expr)}")  # pragma: no cover


def _join_expr(operator: str, operands: list[QueryExpr]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for operand in operands:
        clause, operand_params = _compile_expr(operand)
        clauses.append(f"({clause})")
        params.extend(operand_params)
    return f" {operator} ".join(clauses), params


def _compile_property(prop: PropertyMatch) -> tuple[str, list[Any]]:
    key = prop.key
    if key in _LIVE_ONLY_KEYS:
        raise ArchiveQueryError(
            f"{key}: is only available for live agent queries, not archive queries"
        )
    if key == "text":
        return _compile_text_match(prop.value)
    if key == "status":
        return _like("s.status", prop.value)
    if key == "cl":
        return _like_any(("s.cl_name", "s.meta_changespec"), prop.value)
    if key == "project":
        return _like("s.project_file", prop.value)
    if key == "name":
        return _like_any(("s.agent_name", "s.cl_name", "s.workflow"), prop.value)
    if key == "model":
        return _like("s.model", prop.value)
    if key == "provider":
        return _like("s.llm_provider", prop.value)
    if key == "type":
        value = "run" if prop.value == "running" else prop.value
        return "s.agent_type = ?", [value]
    if key == "source":
        if prop.value == "axe":
            return "(s.workflow IS NOT NULL OR s.is_workflow_child = 1)", []
        return "(s.workflow IS NULL AND s.is_workflow_child = 0)", []
    raise ArchiveQueryError(f"Unsupported archive query key: {key}")


def _compile_text_match(value: str) -> tuple[str, list[Any]]:
    return _like_any(
        (
            "s.cl_name",
            "s.agent_name",
            "s.status",
            "s.model",
            "s.llm_provider",
            "s.project_file",
            "s.workflow",
            "s.meta_changespec",
        ),
        value,
    )


def _like(column: str, value: str) -> tuple[str, list[Any]]:
    return f"LOWER(COALESCE({column}, '')) LIKE ?", [f"%{value.lower()}%"]


def _like_any(columns: tuple[str, ...], value: str) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for column in columns:
        clause, clause_params = _like(column, value)
        clauses.append(clause)
        params.extend(clause_params)
    return "(" + " OR ".join(clauses) + ")", params


def _result_from_row(row: sqlite3.Row) -> ArchiveQueryResult:
    project_file = _optional_str(row["project_file"])
    return ArchiveQueryResult(
        agent_id=str(row["raw_suffix"]),
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        cl_name=str(row["cl_name"]),
        agent_name=_optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=_optional_str(row["start_time"]),
        dismissed_at=None,
        revived_at=None,
        project_name=_project_name(project_file),
        model=_optional_str(row["model"]),
        runtime=None,
        llm_provider=_optional_str(row["llm_provider"]),
        step_index=_optional_int(row["step_index"]),
        step_name=_optional_str(row["step_name"]),
        step_type=None,
        retry_attempt=int(row["retry_attempt"]),
        is_workflow_child=bool(row["is_workflow_child"]),
    )


def _project_name(project_file: str | None) -> str | None:
    if not project_file:
        return None
    parent = Path(project_file).parent.name
    return parent or None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None
