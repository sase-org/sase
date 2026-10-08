"""Marker and metadata persistence shared by the run agent wait barriers.

``waiting.json`` is the Tier 1-projected marker that advertises a parked agent
to the TUI and to the runner-slot queue; ``agent_meta.json`` records the durable
``wait_completed_at`` stamp that makes crossing a barrier idempotent.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import overlay_live_auto_keys
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


def publish_ready_marker(
    artifacts_dir: str,
    payload: dict[str, Any],
) -> bool:
    """Atomically publish ``ready.json``; the first writer wins.

    The payload is written to a hidden temp file in the same directory
    (flushed + fsynced) and then published with a no-clobber
    :func:`os.link`, so a runner can never observe a half-written marker
    and a late tick can never overwrite an existing one.

    Returns ``False`` without writing anything when ``waiting.json`` is
    already gone (the runner released and cleaned up) or when another
    writer published first. Returns ``True`` only when this call
    published. Other :class:`OSError` failures propagate to the caller.
    """
    ready_path = os.path.join(artifacts_dir, "ready.json")
    if not os.path.exists(os.path.join(artifacts_dir, "waiting.json")):
        return False
    fd, temp_name = tempfile.mkstemp(
        prefix=".ready.json.",
        suffix=".tmp",
        dir=artifacts_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temp_name, ready_path)
        except FileExistsError:
            return False
        except OSError:
            if os.path.exists(ready_path):
                return False
            os.replace(temp_name, ready_path)
        return True
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def remove_waiting_marker(artifacts_dir: str) -> None:
    """Delete ``waiting.json`` and refresh the Tier 1 artifact index."""
    try:
        os.unlink(os.path.join(artifacts_dir, "waiting.json"))
    except FileNotFoundError:
        return
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


#: ``wait_release_source`` values stamped into ``agent_meta.json``.
#:
#: - ``startup``: resolved before parking (up-front fast path).
#: - ``ready_json``: released by a ``wait_checks`` ``ready.json`` marker.
#: - ``manual``: released by a marker carrying ``unwait: true`` (TUI run-now).
#: - ``runner_fallback``: released by the runner's periodic direct resolution.
#: - ``timer``: duration-only or until-only waits with no dependencies.
WAIT_RELEASE_SOURCES = (
    "startup",
    "ready_json",
    "manual",
    "runner_fallback",
    "timer",
)

#: Sources whose release latency is measured against the dependency-satisfied
#: instant. ``startup`` resolves synchronously before parking, ``manual`` is
#: an operator action rather than a dependency release, and ``timer`` has no
#: dependencies, so none of them stamp satisfied-at/latency keys.
_LATENCY_MEASURED_SOURCES = ("ready_json", "runner_fallback")


def record_wait_completed_at(
    artifacts_dir: str,
    agent_meta: dict[str, Any],
    *,
    wait_release_source: str | None = None,
    wait_dependencies_satisfied_at: float | None = None,
    wait_released_at: float | None = None,
) -> str:
    """Persist the wait-barrier completion timestamp plus release telemetry.

    The telemetry keys (``wait_release_source``,
    ``wait_dependencies_satisfied_at``, ``wait_release_latency_s``) are
    stamped only in the branch that first stamps ``wait_completed_at``; the
    existing disk-stamp short-circuit (refreshed runner) writes nothing new,
    keeping the stamp idempotent. Satisfied-at/latency keys are recorded
    only for ``ready_json`` / ``runner_fallback`` releases with a known
    satisfied instant.
    """
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
    if wait_release_source in WAIT_RELEASE_SOURCES:
        merged_meta["wait_release_source"] = wait_release_source
        satisfied = (
            float(wait_dependencies_satisfied_at)
            if isinstance(wait_dependencies_satisfied_at, (int, float))
            and not isinstance(wait_dependencies_satisfied_at, bool)
            else None
        )
        if wait_release_source in _LATENCY_MEASURED_SOURCES and satisfied is not None:
            merged_meta["wait_dependencies_satisfied_at"] = satisfied
            if isinstance(wait_released_at, (int, float)) and not isinstance(
                wait_released_at, bool
            ):
                merged_meta["wait_release_latency_s"] = max(
                    0.0, float(wait_released_at) - satisfied
                )
    # Memory-wins merge must not resurrect auto state an ``A`` toggle
    # stripped from disk: the live on-disk auto keys win.
    overlay_live_auto_keys(artifacts_dir, merged_meta, disk_meta=disk_meta)
    agent_meta.update(merged_meta)
    write_agent_meta(artifacts_dir, merged_meta)
    return wait_completed_at
