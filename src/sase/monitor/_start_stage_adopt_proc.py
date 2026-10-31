"""Adopt an already-submitted proc for a staged monitor."""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Any

from ._start_stage_adopt_context import reconstruct_launch_context, revalidate_claim
from ._start_stage_adopt_prepared import bind_staged_prepared_completion
from .models import MonitorError, MonitorRecord
from .start_launch import MonitorLaunchContext
from .start_runtime import monitor_claim_error
from .start_timing import StartTimer


def adopt_existing_proc(
    artifacts_dir: str,
    payload: dict[str, Any],
    claim: dict[str, Any],
    meta: dict[str, Any],
    timer: StartTimer,
) -> MonitorRecord | None:
    """Adopt a proc submitted before member state or the outer receipt.

    Returns the adopted record, or ``None`` when no proc row exists for
    this monitor and the normal submit path must run. A fingerprint
    mismatch is a refusal, never a second launch. A terminal matching
    row is reused as the completed effect. An active row with a live
    supervisor resumes under the same identity after releasing the
    start barrier; an active row with no live supervisor is reconciled
    first, and anything still ambiguous is held for explicit recovery.
    """
    from sase.procs.identity import supervisor_is_alive
    from sase.procs.models import TERMINAL_PROC_STATUSES
    from sase.procs.store import get_proc
    from sase.procs.submission import reconcile_named_procs

    monitor_id = str(payload.get("monitor_id") or "")
    expected_fingerprint = str(payload.get("request_fingerprint") or "")
    if not monitor_id or not expected_fingerprint:
        return None
    try:
        proc = get_proc(monitor_id)
    except Exception as exc:
        raise MonitorError(
            f"could not read existing proc for staged monitor {monitor_id!r} "
            f"({exc}); refusing to launch a second command"
        ) from exc
    if proc is None:
        return None
    if str(proc.request_fingerprint or "") != expected_fingerprint:
        raise MonitorError(
            f"existing proc for staged monitor {monitor_id!r} does not match "
            "the frozen staged request fingerprint; refusing to launch a "
            "second command"
        )
    if proc.status not in TERMINAL_PROC_STATUSES:
        reconcile_named_procs(match=lambda row: row.proc_id == monitor_id)
        try:
            proc = get_proc(monitor_id)
        except Exception as exc:
            raise MonitorError(
                f"could not re-read existing proc for staged monitor "
                f"{monitor_id!r} ({exc}); refusing to launch a second command"
            ) from exc
        if proc is None or proc.status in TERMINAL_PROC_STATUSES:
            return _finalize_adopted_proc(
                artifacts_dir,
                payload,
                claim,
                meta,
                timer,
                proc,
            )
        if not supervisor_is_alive(proc.pid, proc.supervisor_id):
            raise MonitorError(
                f"existing proc for staged monitor {monitor_id!r} has no "
                "live supervisor and its outcome is unknown; refusing to "
                "launch a second command"
            )
        _release_adopt_start_barrier(monitor_id, expected_fingerprint)
    return _finalize_adopted_proc(
        artifacts_dir,
        payload,
        claim,
        meta,
        timer,
        proc,
    )


def _release_adopt_start_barrier(monitor_id: str, fingerprint: str) -> None:
    """Release the start barrier for an adopted live supervisor, if needed.

    A crash between supervisor spawn and barrier release leaves the
    supervisor waiting; releasing the barrier under the lane lock lets
    the already-submitted command run exactly once. A barrier the first
    attempt already released is left untouched.
    """
    from sase.procs.runtime import proc_go_path
    from sase.procs.spawn import write_launch_barrier

    if proc_go_path(monitor_id).exists():
        return
    try:
        write_launch_barrier(monitor_id, request_fingerprint=fingerprint)
    except OSError as exc:
        raise MonitorError(
            f"could not release the start barrier for staged monitor "
            f"{monitor_id!r}: {exc}"
        ) from exc


def _finalize_adopted_proc(
    artifacts_dir: str,
    payload: dict[str, Any],
    claim: dict[str, Any],
    meta: dict[str, Any],
    timer: StartTimer,
    proc: Any | None,
) -> MonitorRecord:
    """Mark the member running for an adopted proc and return its record.

    The dead-supervisor reconciliation owns completion from here: a
    running member whose supervisor is gone is settled honestly (failed
    or lost) with followup settlement, so adopting a terminal row never
    relaunches the command and never invents success.
    """
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    from .staged_owner import clear_staged_owner_index
    from .start_continuation import persist_monitor_start_intent_after_ack

    if proc is None:
        raise MonitorError(
            "staged monitor proc vanished while adopting it; refusing to "
            "launch a second command"
        )
    from sase.procs.models import TERMINAL_PROC_STATUSES

    context = reconstruct_launch_context(artifacts_dir, payload, claim, meta)
    if str(proc.status or "") not in TERMINAL_PROC_STATUSES:
        if proc.pid is None:
            raise MonitorError(
                f"adopted proc for staged monitor {context.monitor_id!r} "
                "has no supervisor pid; refusing to move the workspace claim"
            )
        context = _ensure_adopt_workspace_claim(context, proc.pid)
        context = bind_staged_prepared_completion(context, payload)
    request = context.request
    lane_start = context.lane_start
    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    update_meta_field(artifacts_dir, "pid", proc.pid)
    if proc.supervisor_id:
        update_meta_field(
            artifacts_dir, "monitor_supervisor_identity", proc.supervisor_id
        )
    update_meta_field(artifacts_dir, "monitor_state", "running")
    monitor_id = str(payload.get("monitor_id") or context.monitor_id)
    clear_staged_owner_index(monitor_id)
    record = MonitorRecord(
        monitor_id=context.monitor_id,
        member_agent_name=f"{lane_start.durable_lane}{context.suffix}",
        lane=lane_start.durable_lane,
        project_name=request.project_name,
        artifacts_dir=artifacts_dir,
        timestamp=member_timestamp,
        command=request.command,
        cwd=request.cwd,
        reason=request.reason,
        label=context.label,
        start_status=request.start_status,
        stop_status=request.stop_status,
        timeout_seconds=request.timeout_seconds,
        tail_lines=request.tail_lines,
        idle_timeout_seconds=request.idle_timeout_seconds,
        next_output=request.next_output,
        monitor_state="running",
        next_action=request.next_action or None,
        next_model=request.next_model or None,
        completion_ref=request.completion_ref or None,
        profile=request.profile or None,
        policy_digest=request.policy_digest,
        pid=proc.pid,
        supervisor_identity=proc.supervisor_id,
        request_fingerprint=context.request_fingerprint,
        output_path=str(context.log_path),
        tool_run_id=context.reserved_tool_run_id,
        tool_run_joined=context.tool_run_joined,
    )
    persist_monitor_start_intent_after_ack(
        request,
        record,
        lane_start=lane_start,
        request_fingerprint=context.request_fingerprint,
        starter_artifacts_dir=context.starter_artifacts_dir,
    )
    timer.mark("adopt_existing_proc")
    timer.log(lane_start.durable_lane)
    timer.write(artifacts_dir)
    return record


def _ensure_adopt_workspace_claim(
    context: MonitorLaunchContext, supervisor_pid: int
) -> MonitorLaunchContext:
    """Hold the workspace for an adopted live supervisor.

    A crash inside the original claim move leaves the workspace with
    the dead starter; a crash after it leaves the workspace with the
    supervisor. Only move the claim when the supervisor does not
    already hold it; a failed transfer holds the handoff instead of
    stranding the adopted command without its workspace.
    """
    from sase.running_field import get_claimed_workspaces

    from .start_claim import claim_monitor_workspace

    lane_start = context.lane_start
    project_file = lane_start.project_file
    workspace_num = lane_start.workspace_num
    try:
        claims = [
            item
            for item in get_claimed_workspaces(project_file)
            if item.workspace_num == workspace_num
        ]
    except Exception as exc:
        raise MonitorError(
            f"could not read workspace claims for staged monitor "
            f"{context.monitor_id!r}: {exc}"
        ) from exc
    if any(item.pid == supervisor_pid for item in claims):
        return context
    context = revalidate_claim(context)
    lane_start = context.lane_start
    transfer_from_pid = lane_start.transfer_from_pid
    if transfer_from_pid is not None and not any(
        item.pid == transfer_from_pid for item in claims
    ):
        # The starter's claim is gone; take a fresh claim instead of
        # transferring a ghost pid.
        transfer_from_pid = None
        context = replace(
            context,
            lane_start=replace(lane_start, transfer_from_pid=None),
        )
    member_timestamp = os.path.basename(context.artifacts_dir.rstrip("/"))
    claim = claim_monitor_workspace(
        lane_start.project_file,
        lane_start.workspace_num,
        supervisor_pid=supervisor_pid,
        transfer_from_pid=transfer_from_pid,
        artifacts_timestamp=member_timestamp,
        cl_name=lane_start.cl_name,
    )
    if not claim.result.success:
        raise MonitorError(
            f"could not claim workspace for adopted staged monitor "
            f"{context.monitor_id!r}: "
            f"{monitor_claim_error(lane_start.project_file, lane_start.workspace_num, claim.result.error)}"
        )
    return context
