"""Exact-owner pending-retention facts independent of the settlement adapter.

Crash ordering starts here: persist a minimal exact-owner pending fact
before importing a possibly-stale retention adapter or starting a bounded
fresh interpreter. Stale cleanup honors this fact until a matching guarded
settlement or recovery decision completes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

PENDING_RETENTION_LOCATOR = "diagnostics/pending_workspace_retention.json"
_PENDING_KIND = "pending_workspace_retention"
_SCHEMA_VERSION = 1


def write_pending_retention_identity(
    artifacts_dir: str | None,
    *,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    pid: int,
    reason: str,
    terminal_reason: str = "",
) -> str | None:
    """Persist a pending fact for one exact owner.

    Refuses empty workflow or artifacts-timestamp identities so a wildcard
    cannot protect or target the wrong claim. Returns ``None`` when the
    identity is incomplete or the write fails.
    """
    if not artifacts_dir:
        return None
    if not isinstance(workspace_num, int) or isinstance(workspace_num, bool):
        return None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(workflow, str) or not workflow:
        return None
    if not isinstance(artifacts_timestamp, str) or not artifacts_timestamp:
        return None
    if not isinstance(cl_name, str):
        cl_name = ""
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _PENDING_KIND,
        "workspace_num": workspace_num,
        "workflow": workflow,
        "cl_name": cl_name,
        "artifacts_timestamp": artifacts_timestamp,
        "pid": pid,
        "artifacts_dir": artifacts_dir,
        "terminal_reason": terminal_reason,
        "reason": reason,
        "created_at": time.time(),
    }
    path = Path(artifacts_dir) / PENDING_RETENTION_LOCATOR
    try:
        from sase.core.atomic_json import write_json_marker_atomic

        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_marker_atomic(path, payload)
    except OSError:
        return None
    return str(path)


def read_pending_retention_identity(
    artifacts_dir: str | Path | None,
) -> dict[str, Any] | None:
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
        import json

        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != _PENDING_KIND:
        return None
    return payload


def clear_pending_retention_identity(artifacts_dir: str | Path | None) -> None:
    """Remove a pending-retention fact after settlement or recovery decides."""
    if not artifacts_dir:
        return
    try:
        (Path(artifacts_dir) / PENDING_RETENTION_LOCATOR).unlink()
    except OSError:
        return


def pending_retention_identity_matches(
    pending: dict[str, Any] | None,
    *,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    pid: int,
) -> bool:
    """Check a pending fact names the exact owner awaiting settlement."""
    if not isinstance(pending, dict):
        return False
    pending_workspace = pending.get("workspace_num")
    pending_pid = pending.get("pid")
    if not isinstance(pending_workspace, int) or not isinstance(pending_pid, int):
        return False
    try:
        return (
            pending_workspace == workspace_num
            and str(pending.get("workflow") or "") == workflow
            and str(pending.get("cl_name") or "") == (cl_name or "")
            and str(pending.get("artifacts_timestamp") or "")
            == (artifacts_timestamp or "")
            and pending_pid == pid
        )
    except (TypeError, ValueError):
        return False


__all__ = [
    "PENDING_RETENTION_LOCATOR",
    "clear_pending_retention_identity",
    "pending_retention_identity_matches",
    "read_pending_retention_identity",
    "write_pending_retention_identity",
]
