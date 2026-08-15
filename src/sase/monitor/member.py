"""Create the monitor member's artifacts directory."""

from __future__ import annotations

import json
import os
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)


def create_monitor_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    lane: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    monitor_id: str,
    command: str,
    cwd: str,
    label: str,
    reason: str,
    next_action: str | None,
    start_status: str,
    stop_status: str,
    timeout_seconds: float,
    tail_lines: int,
    next_output: str,
    request_fingerprint: str,
    idle_timeout_seconds: float = 0.0,
    starter_agent: str | None = None,
) -> str:
    """Create a monitor family member's artifacts directory.

    Inherits ``create_followup_artifacts()``-shaped metadata from the
    selected parent artifact (model, provider, workspace, Patch/bead
    lineage, ...) so a later follow-up agent inherits it too, then layers
    on the ``monitor_*`` fields that describe the supervised command
    itself.
    """
    member_name = f"{lane}{suffix}"
    artifacts_dir = create_followup_artifacts(
        project_name,
        base_meta,
        suffix,
        prev_artifacts_timestamp,
        workspace_num=workspace_num,
        agent_name_override=member_name,
        workflow_name=lane,
        agent_family_role="monitor",
    )
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta.update(
        {
            "monitor_id": monitor_id,
            "proc_id": monitor_id,
            "shell_kind": "proc",
            "monitor_command": command,
            "monitor_cwd": cwd,
            "monitor_label": label,
            "monitor_reason": reason,
            "monitor_start_status": start_status,
            "monitor_stop_status": stop_status,
            "monitor_timeout_seconds": timeout_seconds,
            "monitor_tail_lines": tail_lines,
            "monitor_next_output": next_output,
            "monitor_state": "running",
            "monitor_settled": False,
            "monitor_request_fingerprint": request_fingerprint,
        }
    )
    if idle_timeout_seconds > 0:
        meta["monitor_idle_timeout_seconds"] = idle_timeout_seconds
    if next_action:
        meta["monitor_next_action"] = next_action
    if starter_agent:
        meta["monitor_starter_agent"] = starter_agent
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    return artifacts_dir


__all__ = ["create_monitor_member"]
