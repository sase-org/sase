"""Marker and metadata persistence shared by the run agent wait barriers.

``waiting.json`` is the Tier 1-projected marker that advertises a parked agent
to the TUI and to the runner-slot queue; ``agent_meta.json`` records the durable
``wait_completed_at`` stamp that makes crossing a barrier idempotent.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.run_agent_markers import write_agent_meta
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)


def read_json_dict(path: Path) -> dict[str, Any] | None:
    """Load a JSON object from *path*, or None when absent or malformed."""
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def write_waiting_marker(
    artifacts_dir: str,
    waiting_data: dict[str, Any],
) -> None:
    """Publish ``waiting.json`` and refresh the Tier 1 artifact index."""
    waiting_path = os.path.join(artifacts_dir, "waiting.json")
    with open(waiting_path, "w", encoding="utf-8") as f:
        json.dump(waiting_data, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def remove_waiting_marker(artifacts_dir: str) -> None:
    """Delete ``waiting.json`` and refresh the Tier 1 artifact index."""
    try:
        os.unlink(os.path.join(artifacts_dir, "waiting.json"))
    except FileNotFoundError:
        return
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def record_wait_completed_at(
    artifacts_dir: str,
    agent_meta: dict[str, Any],
) -> str:
    """Persist the wait-barrier completion timestamp."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    disk_meta: dict[str, Any] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            disk_meta = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    disk_wait_completed_at = disk_meta.get("wait_completed_at")
    if isinstance(disk_wait_completed_at, str) and disk_wait_completed_at:
        agent_meta["wait_completed_at"] = disk_wait_completed_at
        return disk_wait_completed_at

    memory_wait_completed_at = agent_meta.get("wait_completed_at")
    wait_completed_at = (
        memory_wait_completed_at
        if isinstance(memory_wait_completed_at, str) and memory_wait_completed_at
        else datetime.now(UTC).isoformat()
    )
    merged_meta = {**disk_meta, **agent_meta, "wait_completed_at": wait_completed_at}
    agent_meta.update(merged_meta)
    write_agent_meta(artifacts_dir, merged_meta)
    return wait_completed_at
