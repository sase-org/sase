"""Pending-retention facts written before a risky settlement."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.workspace_retention import WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION

from .types import PENDING_RETENTION_LOCATOR, WorkspaceRetentionOwner


def write_pending_retention(owner: WorkspaceRetentionOwner, reason: str) -> str | None:
    """Record a durable pending-retention fact before a risky settlement.

    Crash ordering starts here: pending evidence, then pinning, then the
    final retention record. Stale cleanup honors an exact-owner pending fact
    until a matching guarded settlement or recovery decision completes.
    """
    if not owner.artifacts_dir:
        return None
    payload: dict[str, object] = {
        "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
        "kind": "pending_workspace_retention",
        "workspace_num": owner.workspace_num,
        "workflow": owner.workflow,
        "cl_name": owner.cl_name,
        "artifacts_timestamp": owner.artifacts_timestamp,
        "pid": owner.pid,
        "artifacts_dir": owner.artifacts_dir,
        "terminal_reason": owner.terminal_reason,
        "reason": reason,
        "created_at": time.time(),
    }
    path = Path(owner.artifacts_dir) / PENDING_RETENTION_LOCATOR
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_marker_atomic(path, payload)
    except OSError:
        return None
    return str(path)


def read_pending_retention(artifacts_dir: str | Path | None) -> dict[str, Any] | None:
    """Read a pending-retention fact; malformed and absent data is ignored."""
    if not artifacts_dir:
        return None
    try:
        raw = (Path(artifacts_dir) / PENDING_RETENTION_LOCATOR).read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "pending_workspace_retention":
        return None
    return payload


def clear_pending_retention(artifacts_dir: str | Path | None) -> None:
    """Remove a pending-retention fact after settlement or recovery decides."""
    if not artifacts_dir:
        return
    try:
        (Path(artifacts_dir) / PENDING_RETENTION_LOCATOR).unlink()
    except OSError:
        return


def pending_retention_matches_owner(
    pending: dict[str, Any] | None, owner: WorkspaceRetentionOwner
) -> bool:
    """Check a pending fact names the exact owner awaiting settlement."""
    if not isinstance(pending, dict):
        return False
    workspace_num = pending.get("workspace_num")
    pid = pending.get("pid")
    if not isinstance(workspace_num, int) or not isinstance(pid, int):
        return False
    try:
        return (
            workspace_num == owner.workspace_num
            and str(pending.get("workflow") or "") == owner.workflow
            and str(pending.get("cl_name") or "") == (owner.cl_name or "")
            and str(pending.get("artifacts_timestamp") or "")
            == (owner.artifacts_timestamp or "")
            and pid == owner.pid
        )
    except (TypeError, ValueError):
        return False


__all__ = [
    "clear_pending_retention",
    "pending_retention_matches_owner",
    "read_pending_retention",
    "write_pending_retention",
]
