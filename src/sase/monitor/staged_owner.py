"""Machine-local index of unstarted staged-monitor ToolRun owners.

A staged monitor owns a reserved ToolRun before its proc exists. Liveness
observation looks this index up by monitor id so a short-lived CLI exit
cannot be treated as launch failure. Adoption and explicit discard remove
the row; held cleanup preserves it for recovery.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

STAGED_OWNER_DIRNAME = "staged-monitor-owners"
STAGED_LAUNCH_PAYLOAD_FILENAME = "staged_monitor_launch.json"


def _staged_owner_index_path(monitor_id: str) -> Path:
    """Return the index path for one staged monitor owner."""
    return sase_home() / STAGED_OWNER_DIRNAME / f"{monitor_id}.json"


def launch_payload_path(artifacts_dir: str) -> Path:
    """Return the member-local frozen launch payload path."""
    return Path(artifacts_dir) / STAGED_LAUNCH_PAYLOAD_FILENAME


def write_staged_owner_index(
    monitor_id: str,
    *,
    staged_id: str,
    artifacts_dir: str,
    starter_artifacts_dir: str | None,
) -> None:
    """Record that *monitor_id* is a pending staged owner."""
    path = _staged_owner_index_path(monitor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "monitor_id": monitor_id,
        "staged_id": staged_id,
        "artifacts_dir": artifacts_dir,
        "starter_artifacts_dir": starter_artifacts_dir,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_staged_owner_index(monitor_id: str) -> dict[str, Any] | None:
    """Return the pending staged-owner row for *monitor_id*, if any."""
    status, payload = probe_staged_owner_index(monitor_id)
    return payload if status == "present" else None


def probe_staged_owner_index(
    monitor_id: str,
) -> tuple[str, dict[str, Any] | None]:
    """Observe the pending-owner row without treating errors as absence.

    Returns ``(status, payload)`` where *status* is ``present``, ``absent``,
    or ``unreadable``. A missing file is confirmed absence. Permission,
    decode, and other probe failures stay ``unreadable``.
    """
    path = _staged_owner_index_path(monitor_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "unreadable", None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "unreadable", None
    if not isinstance(payload, dict):
        return "unreadable", None
    return "present", payload


def clear_staged_owner_index(monitor_id: str) -> None:
    """Drop the pending staged-owner row; safe to repeat."""
    try:
        _staged_owner_index_path(monitor_id).unlink()
    except FileNotFoundError:
        return


def clear_matching_staged_owner_index(monitor_id: str, staged_id: str) -> str:
    """Delete the pending-owner row only when it still names *staged_id*.

    Returns ``cleared``, ``absent``, ``mismatch``, or ``unreadable``. A
    replaced row for a different stage is left untouched.
    """
    path = _staged_owner_index_path(monitor_id)
    status, payload = probe_staged_owner_index(monitor_id)
    if status == "absent":
        return "absent"
    if status != "present" or payload is None:
        return "unreadable"
    if payload.get("staged_id") != staged_id:
        return "mismatch"
    # Re-read immediately before unlink so a replacement staged_id is not
    # deleted by a stale settlement that observed the previous row.
    status, payload = probe_staged_owner_index(monitor_id)
    if status == "absent":
        return "absent"
    if status != "present" or payload is None:
        return "unreadable"
    if payload.get("staged_id") != staged_id:
        return "mismatch"
    try:
        path.unlink()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unreadable"
    return "cleared"


def staged_monitor_member_artifacts_dir(
    monitor_id: str, staged_id: str, payload: Mapping[str, Any]
) -> str | None:
    """Find a staged monitor member from its owner index or frozen payload.

    The payload fallback repairs stages held by older versions that removed
    the index during failed-adoption cleanup.
    """
    try:
        index = read_staged_owner_index(monitor_id)
    except Exception:  # noqa: BLE001 - a missing index can use payload evidence.
        index = None
    if isinstance(index, Mapping) and index.get("staged_id") == staged_id:
        candidate = index.get("artifacts_dir")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    candidate = payload.get("member_artifacts_dir")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    workspace = payload.get("workspace")
    claim_context = (
        workspace.get("claim_context") if isinstance(workspace, Mapping) else None
    )
    candidate = (
        claim_context.get("artifacts_dir")
        if isinstance(claim_context, Mapping)
        else None
    )
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


__all__ = [
    "STAGED_LAUNCH_PAYLOAD_FILENAME",
    "STAGED_OWNER_DIRNAME",
    "clear_matching_staged_owner_index",
    "clear_staged_owner_index",
    "launch_payload_path",
    "probe_staged_owner_index",
    "read_staged_owner_index",
    "staged_monitor_member_artifacts_dir",
    "write_staged_owner_index",
]
