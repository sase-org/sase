"""Thin Python facade over Rust dismissed-agent archive operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_archive_wire import (
    AgentArchiveFacetRequestWire,
    AgentArchiveQueryRequestWire,
    AgentArchiveReviveMarkRequestWire,
    agent_archive_facet_request_to_dict,
    agent_archive_query_request_to_dict,
    agent_archive_revive_mark_request_to_dict,
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


def try_mark_agent_archive_bundles_revived(
    root: Path,
    request: AgentArchiveReviveMarkRequestWire,
) -> dict[str, Any] | None:
    """Mark archive bundles via Rust, or ``None`` if binding is unavailable."""

    try:
        binding = require_rust_binding("mark_agent_archive_bundles_revived")
    except (ImportError, AttributeError):
        return None
    try:
        return dict(
            binding(str(root), agent_archive_revive_mark_request_to_dict(request))
        )
    except (RuntimeError, ValueError):
        return None


def try_verify_agent_archive_index(root: Path) -> dict[str, int | bool] | None:
    """Verify archive index via Rust, or ``None`` if binding is unavailable."""

    try:
        binding = require_rust_binding("verify_agent_archive_index")
    except (ImportError, AttributeError):
        return None
    try:
        payload = dict(binding(str(root)))
    except (RuntimeError, ValueError):
        return None
    return {
        "ok": bool(payload.get("ok", False)),
        "indexed_rows": int(payload.get("indexed_rows", 0)),
        "valid_bundles": int(payload.get("valid_bundles", 0)),
        "corrupt_bundles": int(payload.get("corrupt_bundles", 0)),
        "stale_rows": int(payload.get("stale_rows", 0)),
        "missing_rows": int(payload.get("missing_rows", 0)),
        "fts_missing_rows": int(payload.get("fts_missing_rows", 0)),
        "fts_orphan_rows": int(payload.get("fts_orphan_rows", 0)),
        "payload_hash_mismatches": int(payload.get("payload_hash_mismatches", 0)),
        "orphan_visibility_rows": int(payload.get("orphan_visibility_rows", 0)),
        "orphan_revision_rows": int(payload.get("orphan_revision_rows", 0)),
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
    "try_mark_agent_archive_bundles_revived",
    "try_query_agent_archive",
    "try_verify_agent_archive_index",
]
