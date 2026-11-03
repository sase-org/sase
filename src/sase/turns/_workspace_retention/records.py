"""Durable terminal retention records for workspace settlement."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.workspace_retention import (
    DISPOSITION_OWNERSHIP_MOVED,
    DISPOSITION_RETAIN,
    WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
)

from .types import (
    RETENTION_META_FIELD,
    RETENTION_RECORD_LOCATOR,
    WorkspaceRetentionOwner,
)


def settle_existing_record(
    owner: WorkspaceRetentionOwner, *, reason: str
) -> str | None:
    """Settle a prior retain record after a proven release or transfer."""
    if not owner.artifacts_dir:
        return None
    try:
        from datetime import datetime

        from sase.core.time import get_timezone
        from sase.workspace_provider.retention_record import (
            mark_workspace_retention_settled,
        )

        if not mark_workspace_retention_settled(
            owner.artifacts_dir,
            reason=reason,
            settled_at=datetime.now(get_timezone()).isoformat(),
        ):
            return None
    except Exception:  # noqa: BLE001 - settlement of an old record is best effort
        return None
    return str(Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR)


def persist_record(
    owner: WorkspaceRetentionOwner,
    *,
    disposition: str,
    reason: str,
    affected_repo_ids: Sequence[str],
    snapshot_paths: Sequence[str],
    probe_errors: Sequence[str],
    stale_attempt: bool,
) -> str | None:
    """Write the terminal retention record, preserving settled or unresolved holds."""
    if not owner.artifacts_dir:
        return None
    if disposition == DISPOSITION_RETAIN and _settled_record_path(owner) is not None:
        return _settled_record_path(owner)
    if disposition == DISPOSITION_OWNERSHIP_MOVED:
        # An unresolved retain stays visible until a proven transfer or
        # release settles it. A stale ownership probe is not that proof.
        existing = _unresolved_retain_path(owner)
        if existing is not None:
            return existing
    payload: dict[str, object] = {
        "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
        "kind": "terminal_workspace_retention",
        "workspace_num": owner.workspace_num,
        "project_file": owner.project_file,
        "workflow": owner.workflow,
        "cl_name": owner.cl_name,
        "artifacts_timestamp": owner.artifacts_timestamp,
        "pid": owner.pid,
        "artifacts_dir": owner.artifacts_dir,
        "workspace_dir": owner.checkout_dir,
        "evidence_artifacts_dir": owner.evidence_artifacts_dir,
        "session_id": owner.session_id,
        "turn_id": owner.turn_id,
        "origin_repo_ids": list(owner.origin_repo_ids),
        "staged_id": owner.staged_id,
        "terminal_reason": owner.terminal_reason,
        "disposition": disposition,
        "policy_reason": reason,
        "affected_repo_ids": list(affected_repo_ids),
        "snapshot_paths": list(snapshot_paths),
        "probe_errors": list(probe_errors),
        "stale_attempt": stale_attempt,
        "created_at": time.time(),
    }
    payload.update(_guidance_fields(owner))
    record_path = Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR
    try:
        write_json_marker_atomic(record_path, payload)
    except OSError:
        return None
    _record_meta_path(owner.artifacts_dir, str(record_path))
    return str(record_path)


def _settled_record_path(owner: WorkspaceRetentionOwner) -> str | None:
    """Return the existing settled record path without overwriting it.

    Recovery must not overwrite a settled record with a fresh unresolved
    hold. A record carrying ``settled_at`` (or the legacy ``settled`` flag
    with a transfer marker) stays authoritative.
    """
    if not owner.artifacts_dir:
        return None
    try:
        raw = (Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR).read_text(
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
    if payload.get("kind") != "terminal_workspace_retention":
        return None
    if payload.get("settled_at"):
        return str(Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR)
    if payload.get("settled") is True and (
        payload.get("settled_via") or payload.get("settled_reason")
    ):
        return str(Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR)
    return None


def _unresolved_retain_path(owner: WorkspaceRetentionOwner) -> str | None:
    if not owner.artifacts_dir:
        return None
    try:
        from sase.workspace_provider.retention_record import (
            read_workspace_retention_record,
        )

        record = read_workspace_retention_record(owner.artifacts_dir)
    except Exception:  # noqa: BLE001 - missing records are treated as absent
        return None
    if record is None or not record.unresolved:
        return None
    return str(Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR)


def _guidance_fields(owner: WorkspaceRetentionOwner) -> dict[str, object]:
    """Capture recovery-command facts so surfaces need no extra I/O."""
    extra: dict[str, object] = {}
    if not owner.artifacts_dir:
        return extra
    try:
        raw = json.loads(
            (Path(owner.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        raw = {}
    meta = raw if isinstance(raw, dict) else {}
    name = meta.get("name") or meta.get("agent_name")
    if isinstance(name, str) and name.strip():
        extra["origin_agent_name"] = name.strip()
    is_monitor = owner.workflow == "ace-monitor" or meta.get("turn_kind") == "monitor"
    if not is_monitor:
        return extra
    state = meta.get("monitor_state")
    if not isinstance(state, str) or not state.strip():
        state = owner.terminal_reason
    if isinstance(state, str) and state.strip():
        extra["monitor_state"] = state.strip()
    next_action = meta.get("monitor_next_action")
    if isinstance(next_action, str):
        extra["monitor_next_action"] = next_action.strip()
    host_status = meta.get("monitor_host_completion_status")
    if isinstance(host_status, str) and host_status.strip():
        extra["monitor_host_completion_status"] = host_status.strip()
    return extra


def _record_meta_path(artifacts_dir: str, record_path: str) -> None:
    # Metadata writes are best effort: custody is already protected by the
    # pin above, so a metadata failure must never abort settlement.
    try:
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

        if not (Path(artifacts_dir) / "agent_meta.json").is_file():
            return
        update_meta_field(artifacts_dir, RETENTION_META_FIELD, record_path)
    except Exception:  # noqa: BLE001 - custody outranks metadata
        return


__all__ = ["persist_record", "settle_existing_record"]
