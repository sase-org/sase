"""Monitor-settlement helpers for epic launch completion handoffs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_projects_dir

from sase.bead.epic_launch_handoff_io import (
    artifact_timestamp,
    optional_str,
    read_agent_meta,
    read_json_object,
    utc_now,
)
from sase.bead.epic_launch_handoff_model import CompletionNotificationPayload


def monitor_settlement_payload(
    root_artifacts_dir: str | Path | None,
    monitor_artifacts_dir: str | Path,
    payload: CompletionNotificationPayload,
) -> CompletionNotificationPayload:
    """Return *payload* retargeted to the settled monitor shell."""
    data = dict(payload.action_data)
    monitor_meta = read_agent_meta(monitor_artifacts_dir)
    monitor_cl_name = (
        optional_str(monitor_meta.get("cl_name"))
        or payload.cl_name
        or optional_str(data.get("cl_name"))
    )
    monitor_suffix = artifact_timestamp(monitor_artifacts_dir)
    root_suffix = (
        optional_str(data.get("family_root_suffix"))
        or optional_str(data.get("agent_root_timestamp"))
        or artifact_timestamp(root_artifacts_dir)
        or optional_str(data.get("raw_suffix"))
    )
    if monitor_cl_name:
        data["cl_name"] = monitor_cl_name
    if monitor_suffix:
        data["raw_suffix"] = monitor_suffix
    if root_suffix:
        data["family_root_suffix"] = root_suffix
        data["agent_root_timestamp"] = root_suffix
    return replace(
        payload, cl_name=monitor_cl_name or payload.cl_name, action_data=data
    )


def monitor_terminal_outcome(artifacts_dir: str | Path) -> dict[str, Any] | None:
    artifacts_path = Path(artifacts_dir)
    meta = read_agent_meta(artifacts_path)
    if not meta.get("monitor_settled"):
        return None
    try:
        done = read_json_object(artifacts_path / "done.json")
    except Exception:
        return None
    try:
        workflow_state = read_json_object(artifacts_path / "workflow_state.json")
    except Exception:
        workflow_state = {}
    if workflow_state.get("status") == "running":
        return None
    if not _monitor_refresh_pulse_exists(artifacts_path):
        return None
    monitor_state = optional_str(done.get("monitor_state")) or optional_str(
        meta.get("monitor_state")
    )
    settled_at = optional_str(meta.get("stopped_at")) or utc_now()
    return {
        **({"monitor_state": monitor_state} if monitor_state else {}),
        "settled_at": settled_at,
    }


def _monitor_refresh_pulse_exists(artifacts_dir: str | Path) -> bool:
    try:
        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        return False
    if info is None:
        return False
    pulse_path = (
        sase_projects_dir() / info.project_name / "artifacts" / ".ace_refresh_pulse"
    )
    return pulse_path.exists()
