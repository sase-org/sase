"""Thin Python facade over Rust dismissed-agent archive operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_archive_wire import (
    AgentArchiveFacetRequestWire,
    AgentArchiveQueryRequestWire,
    agent_archive_facet_request_to_dict,
    agent_archive_query_request_to_dict,
)
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class _AgentArchiveQueryResultWire:
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
class _AgentArchiveQueryPageWire:
    results: list[_AgentArchiveQueryResultWire]
    next_cursor: int | None


def try_query_agent_archive(
    root: Path,
    request: AgentArchiveQueryRequestWire,
) -> _AgentArchiveQueryPageWire | None:
    """Return Rust archive query results, or ``None`` if binding is unavailable."""

    try:
        binding = require_rust_binding("query_agent_archive")
    except (ImportError, AttributeError):
        return None
    try:
        payload = binding(str(root), agent_archive_query_request_to_dict(request))
    except (RuntimeError, ValueError):
        return None
    return _page_from_dict(dict(payload))


def try_agent_archive_facet_counts(
    root: Path,
    request: AgentArchiveFacetRequestWire,
) -> dict[str, int] | None:
    """Return Rust archive facet counts, or ``None`` if binding is unavailable."""

    try:
        binding = require_rust_binding("agent_archive_facet_counts")
    except (ImportError, AttributeError):
        return None
    try:
        payload = dict(binding(str(root), agent_archive_facet_request_to_dict(request)))
    except (RuntimeError, ValueError):
        return None
    return {
        str(row.get("value", "")): int(row.get("count", 0))
        for row in payload.get("counts", [])
        if isinstance(row, dict)
    }


def _page_from_dict(payload: dict[str, Any]) -> _AgentArchiveQueryPageWire:
    rows = payload.get("results", [])
    return _AgentArchiveQueryPageWire(
        results=[_result_from_dict(row) for row in rows if isinstance(row, dict)],
        next_cursor=_optional_int(payload.get("next_cursor")),
    )


def _result_from_dict(row: dict[str, Any]) -> _AgentArchiveQueryResultWire:
    return _AgentArchiveQueryResultWire(
        agent_id=str(row["agent_id"]),
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        cl_name=str(row["cl_name"]),
        agent_name=_optional_str(row.get("agent_name")),
        status=str(row["status"]),
        start_time=_optional_str(row.get("start_time")),
        dismissed_at=_optional_str(row.get("dismissed_at")),
        revived_at=_optional_str(row.get("revived_at")),
        project_name=_optional_str(row.get("project_name")),
        model=_optional_str(row.get("model")),
        runtime=_optional_str(row.get("runtime")),
        llm_provider=_optional_str(row.get("llm_provider")),
        step_index=_optional_int(row.get("step_index")),
        step_name=_optional_str(row.get("step_name")),
        step_type=_optional_str(row.get("step_type")),
        retry_attempt=int(row.get("retry_attempt", 0)),
        is_workflow_child=bool(row.get("is_workflow_child", False)),
    )


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
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


__all__ = [
    "try_agent_archive_facet_counts",
    "try_query_agent_archive",
]
