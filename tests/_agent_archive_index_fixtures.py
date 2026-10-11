"""Small SQLite fixtures for the dismissed archive corpus tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sase.ace.dismissed_bundle_index import archive_index_connection


_INSERT_SQL = """
INSERT INTO dismissed_bundle_summaries (
    bundle_path, agent_id, raw_suffix, shard, filename,
    source_username, source_machine, source_run_id,
    archive_visibility, durably_revivable, agent_type, cl_name,
    agent_name, status, start_time, stop_time, dismissed_at,
    agent_session, agent_session_role, agent_clan, agent_clan_generation,
    project_name, model, runtime, llm_provider, workflow,
    is_workflow_child, parent_timestamp, mtime_ns, size_bytes
) VALUES (
    :bundle_path, :agent_id, :raw_suffix, :shard, :filename,
    :source_username, :source_machine, :source_run_id,
    :archive_visibility, :durably_revivable, :agent_type, :cl_name,
    :agent_name, :status, :start_time, :stop_time, :dismissed_at,
    :agent_session, :agent_session_role, :agent_clan, :agent_clan_generation,
    :project_name, :model, :runtime, :llm_provider, :workflow,
    :is_workflow_child, :parent_timestamp, :mtime_ns, :size_bytes
)
"""


def insert_archive_rows(
    root: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Initialize an archive index and insert summary-shaped row mappings."""
    with archive_index_connection(root) as connection:
        connection.executemany(_INSERT_SQL, (_row_values(root, row) for row in rows))


def _row_values(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    run_id = str(row["run_id"])
    name = str(row.get("name") or run_id)
    bundle_path = str(row.get("bundle_path") or root / "bundles" / f"{run_id}.json")
    return {
        "bundle_path": bundle_path,
        "agent_id": name,
        "raw_suffix": str(row.get("raw_suffix") or run_id),
        "shard": run_id[:6],
        "filename": f"{run_id}.json",
        "source_username": str(row.get("source_username") or "bbugyi200"),
        "source_machine": str(row.get("source_machine") or "athena"),
        "source_run_id": run_id,
        "archive_visibility": str(row.get("archive_visibility") or "hidden"),
        "durably_revivable": int(row.get("durably_revivable", 0)),
        "agent_type": str(row.get("agent_type") or "agent"),
        "cl_name": str(row.get("cl_name") or name),
        "agent_name": name,
        "status": str(row.get("status") or "DONE"),
        "start_time": str(row.get("start_time") or "2025-03-02T10:00:00Z"),
        "stop_time": row.get("stop_time", "2025-03-02T10:05:00Z"),
        "dismissed_at": row.get("dismissed_at"),
        "agent_session": row.get("session"),
        "agent_session_role": row.get("role"),
        "agent_clan": row.get("clan"),
        "agent_clan_generation": row.get("clan_generation"),
        "project_name": row.get("project", "sase"),
        "model": row.get("model", "gpt-5"),
        "runtime": row.get("runtime", "300"),
        "llm_provider": row.get("provider", "codex"),
        "workflow": row.get("workflow"),
        "is_workflow_child": int(bool(row.get("workflow_child", False))),
        "parent_timestamp": row.get("parent_timestamp"),
        "mtime_ns": 0,
        "size_bytes": 0,
    }


__all__ = ["insert_archive_rows"]
