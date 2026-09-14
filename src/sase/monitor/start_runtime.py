"""Runtime helper operations for the monitor-start transaction."""

from __future__ import annotations

import os
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.monitor_state import monitor_state_bucket
from sase.procs.runtime import proc_started_path, read_json_object
from sase.running_field import get_claimed_workspaces
from sase.shells.settlement import stamp_shell_finished_at
from sase.workflows.utils import get_project_file_path

from .request import DEFAULT_STOP_STATUS
from .settlement import finalize_monitor_workflow_state, project_name_from_artifacts_dir
from .start_metadata import read_start_meta


def supervisor_pid(proc: Any) -> int | None:
    """Return the supervisor pid from the proc row or its start acknowledgement."""
    if isinstance(proc.pid, int):
        return proc.pid
    started = read_json_object(proc_started_path(proc.proc_id))
    raw = started.get("pid")
    return raw if isinstance(raw, int) else None


def proc_timeout_seconds(value: float) -> int | None:
    """Convert a monitor timeout to the integer seconds the proc wire stores."""
    if value <= 0:
        return None
    return max(1, int(round(value)))


def teardown_failed_member(artifacts_dir: str, error: str) -> None:
    """Mark a half-created monitor member failed rather than phantom-running."""
    meta = read_start_meta(artifacts_dir)
    meta["monitor_state"] = "failed"
    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "monitor_state": "failed",
        "error": error,
        "status_label": meta.get("monitor_stop_status") or DEFAULT_STOP_STATUS,
        "status_bucket": monitor_state_bucket("failed"),
    }
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    stamp_shell_finished_at(done_marker)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_monitor_workflow_state(artifacts_dir)


def monitor_claim_error(
    project_file: str,
    workspace_num: int,
    error: str | None,
) -> str:
    base = error or f"workspace #{workspace_num} claim rejected"
    if workspace_num == 0:
        return base

    conflicts = [
        claim
        for claim in get_claimed_workspaces(project_file)
        if claim.workspace_num == workspace_num
    ]
    if not conflicts:
        return base

    details = "; ".join(
        f"#{claim.workspace_num} pid {claim.pid} workflow {claim.workflow}"
        f" cl {claim.cl_name or '(none)'}"
        for claim in conflicts
    )
    return f"{base}; conflicting RUNNING claim: {details}"


__all__ = [
    "monitor_claim_error",
    "proc_timeout_seconds",
    "supervisor_pid",
    "teardown_failed_member",
]
