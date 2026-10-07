"""Marker and metadata persistence shared by the run agent wait barriers.

``waiting.json`` is the Tier 1-projected marker that advertises a parked agent
to the TUI and to the runner-slot queue; ``agent_meta.json`` records the durable
``wait_completed_at`` stamp that makes crossing a barrier idempotent.
"""

import json
import os
from collections.abc import Mapping
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


def queue_capacity_marker_fields(
    queue_capacity: int | None,
    *,
    explicit: bool,
    queue_capacity_multiplier: float | None = None,
) -> dict[str, Any]:
    """Return canonical ``waiting.json`` capacity fields.

    Readers still accept legacy ``wait_runners`` spellings. Writers emit only
    ``queue_capacity`` now that the scanner projects the canonical keys.
    """
    if queue_capacity is None and queue_capacity_multiplier is not None:
        return {"queue_capacity_multiplier": queue_capacity_multiplier}
    fields: dict[str, Any] = {"queue_capacity_explicit": explicit}
    if queue_capacity is not None:
        fields["queue_capacity"] = queue_capacity
    return fields


def hold_marker_fields(blockers: object) -> dict[str, Any]:
    """Return ``waiting.json`` hold fields for the active hold-barrier blocker.

    ``held_by``/``hold_expires_at`` are written by the candidate's own runner
    (same writer, same file) from the decision blockers Rust already
    evaluated, so a fresh poll self-heals a stale value once the hold
    releases: an empty dict clears both fields.
    """
    if isinstance(blockers, list):
        for blocker in blockers:
            if not isinstance(blocker, dict) or blocker.get("code") != "hold-barrier":
                continue
            fields: dict[str, Any] = {}
            held_by = blocker.get("held_by")
            if isinstance(held_by, str) and held_by:
                fields["held_by"] = held_by
            hold_expires_at = blocker.get("hold_expires_at")
            if isinstance(hold_expires_at, (int, float)) and not isinstance(
                hold_expires_at, bool
            ):
                fields["hold_expires_at"] = hold_expires_at
            return fields
    return {}


#: ``waiting.json`` fields that park an agent on a dependency. A marker carrying
#: any non-empty one of these must nudge the project refresh pulse so the
#: ``wait_checks`` fs trigger fires; pure runner-slot queue markers carry none
#: of them and must not cause wake churn. ``wait_for_epics_of`` is a subset of
#: ``waiting_for`` by construction but is listed so a lone epics marker still
#: counts as a dependency wait.
_DEPENDENCY_WAIT_FIELDS = (
    "waiting_for",
    "wait_for_artifacts",
    "wait_for_fork_sources",
    "wait_for_epics_of",
    "wait_for_beads",
    "wait_for_hoods",
)


def waiting_payload_has_dependencies(payload: Mapping[str, Any]) -> bool:
    """Return True when a ``waiting.json`` payload parks on dependencies."""
    for key in _DEPENDENCY_WAIT_FIELDS:
        value = payload.get(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            if len(value):
                return True
        elif value:
            return True
    return False


def touch_project_refresh_pulse_for_artifacts_dir(artifacts_dir: str) -> None:
    """Nudge the project refresh pulse best-effort; never raises."""
    try:
        from sase.turns.settlement import (
            project_name_from_artifacts_dir,
            touch_turn_refresh_pulse,
        )

        touch_turn_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
    except Exception:  # noqa: BLE001 - pulse must never fail the marker write
        pass


def write_waiting_marker(
    artifacts_dir: str,
    waiting_data: dict[str, Any],
) -> None:
    """Publish ``waiting.json`` and refresh the Tier 1 artifact index."""
    payload = dict(waiting_data)
    payload.pop("wait_runners", None)
    payload.pop("wait_runners_explicit", None)
    waiting_path = os.path.join(artifacts_dir, "waiting.json")
    with open(waiting_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    if waiting_payload_has_dependencies(payload):
        touch_project_refresh_pulse_for_artifacts_dir(artifacts_dir)


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
