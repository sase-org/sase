"""Terminal settlement for the detached monitor supervisor.

Writes the terminal marker, saves chat history, and settles the workspace
claim once the monitored command has exited (or the supervisor has decided
its final state without running it).
"""

from __future__ import annotations

import os
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.bead.epic_launch_handoff import publish_deferred_monitor_completion
from sase.continuation_capture import persist_monitor_result_best_effort
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.history.chat import save_chat_history
from sase.logs.pipe import BoundedLogRetention
from sase.monitor_state import monitor_state_bucket
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)
from sase.turns.followup import wait_for_followup_started
from sase.turns.settlement import stamp_turn_finished_at
from sase.workflows.utils import get_project_file_path

from ._supervise_shared import TimeoutKind, format_duration, utc_now_iso
from .diagnostics import (
    assemble_diagnostic_manifest,
    diagnostic_manifest_path,
    freeze_retained_log_metadata,
    retained_log_metadata_path,
)
from .followup import launch_followup_agent
from .logs import monitor_log_path
from .models import MonitorState
from .output import OutputCapture
from .settlement import (
    finalize_monitor_workflow_state,
    project_name_from_artifacts_dir,
    settle_claim_and_followup,
    touch_monitor_refresh_pulse,
)


def finish_monitor(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    error: str | None,
    timeout_kind: TimeoutKind | None,
    retention: BoundedLogRetention | None,
) -> None:
    """Write the terminal marker, save chat history, and settle the claim."""
    raw_stop = meta.get("monitor_stop_status")
    stop_status = clamp_monitor_status_or_default(
        raw_stop if isinstance(raw_stop, str) else None,
        default=DEFAULT_MONITOR_STOP_STATUS,
    )
    retained = capture.retained_text()

    meta["monitor_state"] = monitor_state
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    meta["monitor_output_truncated"] = capture.truncated
    stopped_at = utc_now_iso()
    timeout_message = _timeout_message(
        timeout_kind,
        total_timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        idle_timeout_seconds=float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        elapsed_seconds=elapsed_seconds,
    )
    if timeout_kind is not None:
        meta["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            meta["monitor_timeout_message"] = timeout_message
    monitor_id = str(meta.get("monitor_id") or "monitor")
    diagnostic_manifest = assemble_diagnostic_manifest(
        artifacts_dir,
        monitor_id=monitor_id,
        complete=monitor_state == "completed",
    )
    retained_log = freeze_retained_log_metadata(
        artifacts_dir,
        output_path=monitor_log_path(artifacts_dir),
        monitor_id=monitor_id,
        retention=retention,
    )
    meta["monitor_diagnostic_manifest_path"] = str(
        diagnostic_manifest_path(artifacts_dir)
    )
    meta["monitor_diagnostic_manifest_ref"] = diagnostic_manifest.get("manifest_ref")
    meta["monitor_retained_log_metadata_path"] = str(
        retained_log_metadata_path(artifacts_dir)
    )
    meta["monitor_retained_log_ref"] = retained_log.get("log_ref")
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    persist_monitor_result_best_effort(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        stopped_at=stopped_at,
        diagnostic_manifest=diagnostic_manifest,
        retained_log=retained_log,
        timeout_kind=timeout_kind,
        project_name=project_name,
        update_meta=False,
    )
    persisted_meta = dict(meta)
    persisted_meta.pop("stopped_at", None)
    write_agent_meta_atomic(
        artifacts_dir,
        persisted_meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    meta["stopped_at"] = stopped_at

    member_name = str(meta.get("name") or "")
    timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    response_path = save_chat_history(
        f"sase monitor start --command {meta.get('monitor_command')!r} "
        f"--reason {meta.get('monitor_reason')!r}",
        retained,
        "ace-run",
        agent=member_name,
        timestamp=timestamp,
        branch_or_workspace=meta.get("cl_name"),
        metadata_agent=member_name,
        metadata_model=meta.get("model"),
        metadata_llm_provider=meta.get("llm_provider"),
    )

    followup_settlement = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        capture=capture,
        timeout_kind=timeout_kind,
        project_name=project_name,
        launch_followup=launch_followup_agent,
    )
    if getattr(followup_settlement, "hijack_handled", False):
        if getattr(followup_settlement, "hijack_settled", False):
            finalize_monitor_workflow_state(artifacts_dir)
            touch_monitor_refresh_pulse(project_name)
            publish_deferred_monitor_completion(
                artifacts_dir,
                outcome={
                    "monitor_state": monitor_state,
                    "settled_at": utc_now_iso(),
                    "hijack_id": followup_settlement.hijack_id,
                },
            )
        return
    followup_error = followup_settlement.error
    followup_launch = followup_settlement.launch_result
    if (
        followup_launch is not None
        and followup_launch.launched
        and followup_launch.artifacts_dir
    ):
        wait_for_followup_started(followup_launch.artifacts_dir, followup_launch.pid)

    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "name": meta.get("name"),
        "cl_name": meta.get("cl_name"),
        "workspace_dir": meta.get("workspace_dir"),
        "workspace_num": meta.get("workspace_num"),
        "monitor_state": monitor_state,
        "monitor_exit_code": exit_code,
        "monitor_elapsed_seconds": elapsed_seconds,
        "status_label": stop_status,
        "status_bucket": monitor_state_bucket(monitor_state),
        "response_path": response_path,
    }
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    if error:
        done_marker["error"] = error
    if followup_error:
        done_marker["monitor_followup_error"] = followup_error
    for key in (
        "monitor_followup_outcome",
        "monitor_followup_degraded_reason",
        "monitor_followup_prompt_path",
        "monitor_worktree_recovery_diff_path",
        "monitor_id",
        "monitor_host_completion_status",
        "monitor_host_completion_message",
        "monitor_host_completion_reason",
        "monitor_host_completion_reasons",
    ):
        if meta.get(key):
            done_marker[key] = meta[key]
    if timeout_kind is not None:
        done_marker["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            done_marker["monitor_timeout_message"] = timeout_message
    for key in (
        "monitor_diagnostic_manifest_path",
        "monitor_diagnostic_manifest_ref",
        "monitor_retained_log_metadata_path",
        "monitor_retained_log_ref",
        "continuation_monitor_result_id",
        "continuation_monitor_result_ref",
        "continuation_monitor_result_path",
        "continuation_monitor_result_sha256",
        "continuation_monitor_result_node_id",
        "continuation_monitor_result_node_ref",
        "continuation_monitor_result_manifest_ref",
        "continuation_monitor_result_manifest_path",
        "continuation_node_id",
        "continuation_node_ref",
        "continuation_manifest_ref",
        "continuation_manifest_path",
    ):
        if meta.get(key):
            done_marker[key] = meta[key]
    stamp_turn_finished_at(done_marker)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_monitor_workflow_state(artifacts_dir)

    touch_monitor_refresh_pulse(project_name)
    publish_deferred_monitor_completion(
        artifacts_dir,
        outcome={
            "monitor_state": monitor_state,
            "settled_at": utc_now_iso(),
        },
    )


def _timeout_message(
    timeout_kind: TimeoutKind | None,
    *,
    total_timeout_seconds: float,
    idle_timeout_seconds: float,
    elapsed_seconds: float,
) -> str | None:
    if timeout_kind == "idle":
        return f"no output for {format_duration(idle_timeout_seconds)}"
    if timeout_kind == "total":
        elapsed = format_duration(elapsed_seconds)
        total = format_duration(total_timeout_seconds)
        return f"did not finish after {elapsed} of a {total} budget"
    return None


__all__ = [
    "finish_monitor",
]
