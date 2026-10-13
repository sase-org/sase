"""Bundle-backed fixtures for archive corpus tests."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sase.ace.dismissed_bundle_index import rebuild_index, upsert_bundle_summary

_SHARD_RE = re.compile(r"^\d{6}$")


def insert_archive_rows(
    root: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Write synthetic bundles and index them through the Rust adapter."""

    pending: list[tuple[Path, dict[str, Any]]] = []
    for row in rows:
        run_id = str(row["run_id"])
        name = str(row.get("name") or run_id)
        bundle_path = Path(row.get("bundle_path") or root / f"{run_id}.json")
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle = _bundle_for_row(row, run_id, name)
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        pending.append((bundle_path, bundle))

    if not pending:
        return

    rebuild_index(root)
    for bundle_path, bundle in pending:
        if not _is_discovered_by_rebuild(root, bundle_path):
            if not upsert_bundle_summary(root, bundle_path, bundle):
                raise AssertionError(f"failed to index fixture bundle {bundle_path}")


def _bundle_for_row(row: Mapping[str, Any], run_id: str, name: str) -> dict[str, Any]:
    project = row.get("project", "sase")
    return {
        "raw_suffix": str(row.get("raw_suffix") or run_id),
        "source_username": str(row.get("source_username") or "bbugyi200"),
        "source_machine": str(row.get("source_machine") or "athena"),
        "source_run_id": run_id,
        "agent_type": str(row.get("agent_type") or "agent"),
        "cl_name": str(row.get("cl_name") or name),
        "agent_name": name,
        "status": str(row.get("status") or "DONE"),
        "start_time": row.get("start_time", "2025-03-02T10:00:00Z"),
        "stop_time": row.get("stop_time", "2025-03-02T10:05:00Z"),
        "dismissed_at": row.get("dismissed_at"),
        "agent_session": row.get("session"),
        "agent_session_role": row.get("role"),
        "agent_clan": row.get("clan"),
        "agent_clan_generation": row.get("clan_generation"),
        "project_file": (
            f"/projects/{project}/{project}.sase" if project is not None else None
        ),
        "model": row.get("model", "gpt-5"),
        "workflow": row.get("workflow", row.get("runtime")),
        "llm_provider": row.get("provider", "codex"),
        "archive_schema_version": 1,
        "archive_visibility": str(row.get("archive_visibility") or "hidden"),
        "is_workflow_child": bool(row.get("workflow_child", False)),
        "parent_timestamp": row.get("parent_timestamp"),
    }


def _is_discovered_by_rebuild(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return len(relative.parts) == 1 or (
        len(relative.parts) == 2 and _SHARD_RE.fullmatch(relative.parts[0]) is not None
    )


__all__ = ["insert_archive_rows"]
