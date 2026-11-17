"""Settle monitor follow-up ownership and write terminal markers."""

from __future__ import annotations

from typing import Any

from sase.agent._user_kill_intent import read_recorded_scratch_key
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.bead.epic_launch_handoff import publish_deferred_monitor_completion
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.monitor_state import monitor_state_bucket
from sase.monitor_status import clamp_monitor_status_or_default
from sase.procs.store import get_proc
from sase.turns.followup import wait_for_followup_started
from sase.turns.settlement import stamp_turn_finished_at
from sase.workflows.utils import get_project_file_path

from ._proc_adapter_helpers import (
    capture_from_log,
    command_ended_at,
    read_meta,
    utc_now_iso,
)
from .followup import launch_followup_agent
from .models import MonitorState
from .output import OutputCapture
from .request import DEFAULT_STOP_STATUS
from .settlement import (
    finalize_monitor_workflow_state,
    project_name_from_artifacts_dir,
    settle_claim_and_followup,
    touch_monitor_refresh_pulse,
)


def _settle_followup_serialized(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    timeout_kind: str | None,
    project_name: str | None,
    transfer_from_pid: int | None,
) -> Any:
    lane = meta.get("agent_session")
    if (
        isinstance(project_name, str)
        and project_name
        and isinstance(lane, str)
        and lane
    ):
        from sase.agent.hijack.locks import acquire_monitor_lane_lock

        with acquire_monitor_lane_lock(project_name, lane):
            return settle_claim_and_followup(
                artifacts_dir,
                meta,
                monitor_state=monitor_state,
                exit_code=exit_code,
                elapsed_seconds=elapsed_seconds,
                capture=capture,
                timeout_kind=timeout_kind,
                project_name=project_name,
                transfer_from_pid=transfer_from_pid,
                launch_followup=launch_followup_agent,
            )
    return settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        capture=capture,
        timeout_kind=timeout_kind,
        project_name=project_name,
        transfer_from_pid=transfer_from_pid,
        launch_followup=launch_followup_agent,
    )


def settle_monitor_followup(state: dict[str, Any]) -> None:
    """Launch or suppress ``--next`` and write the terminal agent-session markers."""
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        state["followup_outcome"] = None
        return
    meta = read_meta(artifacts_dir)
    if state.get("monitor_meta"):
        meta.update(state["monitor_meta"])
    _cleanup_starter_cargo_target(meta)
    monitor_state = str(
        state.get("monitor_state") or meta.get("monitor_state") or "failed"
    )
    exit_code = state.get("monitor_exit_code")
    if not isinstance(exit_code, int):
        exit_code = meta.get("monitor_exit_code")
        exit_code = exit_code if isinstance(exit_code, int) else None
    elapsed = float(state.get("monitor_elapsed_seconds") or 0.0)
    timeout_kind = state.get("monitor_timeout_kind")
    if not isinstance(timeout_kind, str):
        timeout_kind = meta.get("monitor_timeout_kind")
        timeout_kind = timeout_kind if isinstance(timeout_kind, str) else None
    log_path = str(state.get("log_path") or meta.get("monitor_output_path") or "")
    capture = capture_from_log(log_path)
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    transfer_from_pid = _transfer_pid(state)

    tool_run_id = meta.get("monitor_tool_run_id")
    # A joined run is owned by its executing detached proc, never by this
    # monitor: settling it as monitor-owned would steal the owner's
    # reconcile. The join worker and the starter watchdog converge on its
    # settlement instead.
    joined = meta.get("monitor_tool_run_joined") is True
    if isinstance(tool_run_id, str) and tool_run_id and not joined:
        # Reconcile before the follow-up decision so a resumed settlement
        # also settles a hand-off run whose worker died. Never notifies and
        # never touches the continuation.
        from sase.tool.settlement import settle_monitor_tool_run

        settle_monitor_tool_run(
            tool_run_id,
            str(meta.get("monitor_id") or state.get("proc_id") or ""),
            state,
        )

    from .hijack_settlement import monitor_hijack_pending

    if meta.get("monitor_followup_outcome") and not monitor_hijack_pending(
        artifacts_dir, meta
    ):
        state["followup_outcome"] = meta.get("monitor_followup_outcome")
    else:
        followup_settlement = _settle_followup_serialized(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,  # type: ignore[arg-type]
            exit_code=exit_code,
            elapsed_seconds=elapsed,
            capture=capture,
            timeout_kind=timeout_kind,
            project_name=project_name,
            transfer_from_pid=transfer_from_pid,
        )
        followup_error = followup_settlement.error
        followup_launch = followup_settlement.launch_result
        if (
            followup_launch is not None
            and followup_launch.launched
            and followup_launch.artifacts_dir
        ):
            wait_for_followup_started(
                followup_launch.artifacts_dir,
                followup_launch.pid,
            )
        state["followup_error"] = followup_error
        state["followup_outcome"] = meta.get("monitor_followup_outcome")

        if getattr(followup_settlement, "hijack_handled", False):
            if getattr(followup_settlement, "hijack_settled", False):
                state["followup_outcome"] = "hijacked"
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

    if not meta.get("stopped_at"):
        meta["stopped_at"] = command_ended_at(
            state,
            meta=meta,
            proc=get_proc(str(state.get("proc_id") or meta.get("monitor_id") or "")),
        )
    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    raw_stop = meta.get("monitor_stop_status")
    stop_status = clamp_monitor_status_or_default(
        raw_stop if isinstance(raw_stop, str) else None,
        default=DEFAULT_STOP_STATUS,
    )
    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "name": meta.get("name"),
        "cl_name": meta.get("cl_name"),
        "workspace_dir": meta.get("workspace_dir"),
        "workspace_num": meta.get("workspace_num"),
        "monitor_state": monitor_state,
        "monitor_exit_code": exit_code,
        "monitor_elapsed_seconds": elapsed,
        "status_label": stop_status,
        "status_bucket": monitor_state_bucket(monitor_state),
        "response_path": state.get("response_path"),
    }
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    error = state.get("monitor_error") or state.get("followup_error")
    if error:
        done_marker["error"] = error
    followup_error = state.get("followup_error")
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
    timeout_kind = state.get("monitor_timeout_kind")
    timeout_message = state.get("monitor_timeout_message")
    if timeout_kind:
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


def _cleanup_starter_cargo_target(meta: dict[str, Any]) -> None:
    """Reclaim an unheld starter cargo target before launching a follow-up."""
    # Deferred to keep the scratch reaper out of the TUI import closure
    # (import budget).
    from sase.axe.run_agent_runner_scratch import cleanup_launch_scratch_key

    if meta.get("monitor_tool_run_joined") is True:
        cleanup_launch_scratch_key(
            None,
            buckets=("cargo-targets",),
            context="monitor-settlement",
            skip_reason="joined-monitor",
        )
        return
    try:
        # The launch key belongs to the starter; monitor members do not record it.
        starter_dir = meta.get("monitor_starter_artifacts_dir")
        scratch_key = (
            read_recorded_scratch_key(starter_dir)
            if isinstance(starter_dir, str) and starter_dir
            else None
        )
    except Exception as exc:  # noqa: BLE001 - scratch cleanup never blocks settlement
        cleanup_launch_scratch_key(
            None,
            buckets=("cargo-targets",),
            context="monitor-settlement",
            skip_reason="scratch-key-read-error",
            error=f"{type(exc).__qualname__}: {exc}",
        )
        return
    cleanup_launch_scratch_key(
        scratch_key,
        buckets=("cargo-targets",),
        context="monitor-settlement",
    )


def _transfer_pid(state: dict[str, Any]) -> int | None:
    claim = state.get("workspace_claim")
    if isinstance(claim, dict):
        raw = claim.get("supervisor_pid")
        if isinstance(raw, int):
            return raw
    proc = get_proc(str(state.get("proc_id") or ""))
    return proc.pid if proc is not None else None
