"""The monitor-start launch: proc submit, claim moves, and the running record.

Split out of :mod:`sase.monitor.start`: once
:func:`sase.monitor.start_flow.start_monitor` has created the member, this
module resolves the proc argv (joining an existing ToolRun or reserving a new
one), submits the supervisor proc, moves the workspace claim, and builds the
running record -- tearing the member back down when any of those steps fails.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.identity import discover_agent_runtime
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.bead.epic_launch_handoff import MONITOR_ARTIFACTS_ENV
from sase.config._settings import get_monitor_tool_wrap
from sase.procs.models import ARTIFACTS_LOG_OWNER
from sase.procs.request import ProcSubmitRequest
from sase.procs.spawn import DetachedSupervisor
from sase.procs.submission import ProcSubmitError, submit_proc_request

from . import store_lane
from .claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from .diagnostics import diagnostics_dir
from .logs import append_monitor_log_bytes
from .models import (
    MonitorError,
    MonitorRecord,
)
from .proc_adapter import (
    MONITOR_FOLLOWUP_KIND,
    MONITOR_PROC_ORIGIN,
)
from .request import StartMonitorRequest
from .start_claim import (
    claim_monitor_workspace,
    undo_monitor_claim,
)
from .start_continuation import persist_monitor_start_intent_after_ack
from .start_lane import LaneStart
from .start_runtime import (
    monitor_claim_error,
    proc_timeout_seconds,
    supervisor_pid,
    teardown_failed_member,
)
from .start_timing import StartTimer
from .tool_wrap import (
    format_unwrapped_log_line,
    monitor_tool_run_words,
    resolve_monitor_tool_wrap,
)


@dataclass(frozen=True)
class MonitorLaunchContext:
    """Everything the launch needs after the flow created the member."""

    request: StartMonitorRequest
    lane_start: LaneStart
    label: str
    records_enabled: bool
    starter_artifacts_dir: str | None
    request_fingerprint: str
    monitor_id: str
    suffix: str
    bound_completion_ref: str | None
    artifacts_dir: str
    log_path: Path


def _tool_run_agent_overlay(starter_agent: str | None) -> dict[str, str]:
    """Return the attribution overlay carrying a monitor's starter agent.

    Passed as ``SASE_TOOL_RUN_AGENT`` so a monitor-owned ``sase tool run``
    records its starter without restoring ``SASE_AGENT*`` (which would flip
    compact output back on inside an owner). ``SASE_TOOL_RUN_PROVIDER``
    carries the starter's provider for the same reason, when known; ceilings
    are never forwarded, because a monitor has none. Both are scrubbed at
    agent launch like every other ``SASE_TOOL_*`` variable.
    """
    overlay: dict[str, str] = {}
    if starter_agent and starter_agent.strip():
        overlay["SASE_TOOL_RUN_AGENT"] = starter_agent.strip()
    try:
        provider = discover_agent_runtime()
    except Exception:  # noqa: BLE001 - provider attribution is best effort.
        provider = None
    if provider:
        overlay["SASE_TOOL_RUN_PROVIDER"] = provider
    return overlay


def _record_monitor_join(
    run_id: str,
    monitor_id: str,
    *,
    artifacts_dir: str,
    bound_completion_ref: str | None,
) -> None:
    """Record the Rust join for a ``-J/--join`` start, or tear down and raise.

    Runs inside the lane start lock, after the member exists and before the
    proc submits, so the join and the member appear atomically. A refusal
    rolls the member back (plus any bound prepared completion) and raises
    :class:`MonitorError` with the run's state and a ``sase tool show``
    pointer; the handler maps it to exit ``1`` with no monitor started.
    """

    from sase.core.tool_run import tool_run_join

    from .join import show_pointer

    caller = (os.environ.get("SASE_AGENT_NAME") or "").strip()
    join_request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "joiner_kind": "monitor",
        "joiner_id": monitor_id,
        "requested_by": caller or "sase",
    }
    if caller:
        join_request["agent"] = caller
    try:
        result = tool_run_join(join_request)
    except Exception as exc:  # noqa: BLE001 - a failed join starts no monitor.
        _teardown_refused_join(
            artifacts_dir, bound_completion_ref, monitor_id, str(exc)
        )
        raise MonitorError(
            f"could not join tool run {run_id} ({exc}); "
            f"no monitor started ({show_pointer(run_id)})"
        ) from exc
    if not isinstance(result, dict) or result.get("outcome") != "joined":
        refusal = (
            str(result.get("refusal") or "refused")
            if isinstance(result, dict)
            else "refused"
        )
        run = result.get("run") if isinstance(result, dict) else None
        message = _join_refusal_message(run_id, refusal, run)
        _teardown_refused_join(artifacts_dir, bound_completion_ref, monitor_id, message)
        raise MonitorError(message)


def _join_refusal_message(run_id: str, refusal: str, run: Any) -> str:
    """Render a join refusal with state and a ``sase tool show`` pointer."""

    from .join import show_pointer

    pointer = show_pointer(run_id)
    state = str(run.get("state") or "") if isinstance(run, dict) else ""
    if refusal == "settled":
        return (
            f"tool run {run_id} is already {state or 'settled'}; "
            f"nothing to join ({pointer})"
        )
    if refusal == "stop_requested":
        return (
            f"tool run {run_id} already has a stop request; nothing to join ({pointer})"
        )
    if refusal == "joined_elsewhere":
        join = run.get("join") if isinstance(run, dict) else None
        other = ""
        if isinstance(join, dict) and str(join.get("id") or ""):
            other = f" by {join.get('kind')} {join.get('id')}"
        return (
            f"tool run {run_id} is already joined{other}; nothing to join ({pointer})"
        )
    return f"tool run {run_id} cannot be joined ({refusal}); no monitor started ({pointer})"


def _teardown_refused_join(
    artifacts_dir: str,
    bound_completion_ref: str | None,
    monitor_id: str,
    message: str,
) -> None:
    """Roll back the member (and any bound completion) for a refused join."""

    if bound_completion_ref is not None:
        from sase.finalizers.prepare import rollback_prepared_completion

        rollback_prepared_completion(
            bound_completion_ref,
            monitor_id=monitor_id,
            artifacts_dir=store_lane.caller_artifacts_dir(),
        )
    teardown_failed_member(artifacts_dir, message)


def _release_monitor_join(run_id: str, monitor_id: str) -> None:
    """Release a recorded join after a failed submit; best effort."""

    from sase.core.tool_run import tool_run_release_join

    try:
        tool_run_release_join(
            {
                "schema_version": 1,
                "run_id": run_id,
                "joiner_kind": "monitor",
                "joiner_id": monitor_id,
            }
        )
    except Exception:  # noqa: BLE001 - the teardown below reports the failure.
        pass


def launch_monitor(context: MonitorLaunchContext, timer: StartTimer) -> MonitorRecord:
    """Submit the monitor proc and build the running record for *context*.

    The caller holds the lane start lock for the whole call, so the join (if
    any), the member, and the proc submit appear atomically. Every failure
    below tears the half-created member back down and raises
    :class:`MonitorError`.
    """
    request = context.request
    lane_start = context.lane_start
    label = context.label
    records_enabled = context.records_enabled
    starter_artifacts_dir = context.starter_artifacts_dir
    request_fingerprint = context.request_fingerprint
    monitor_id = context.monitor_id
    suffix = context.suffix
    bound_completion_ref = context.bound_completion_ref
    artifacts_dir = context.artifacts_dir
    log_path = context.log_path
    durable_lane = lane_start.durable_lane

    member_name = f"{durable_lane}{suffix}"
    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    claim_holder: dict[str, Any] = {}

    def after_spawn(supervisor: DetachedSupervisor) -> None:
        if supervisor.pid == os.getpid():
            raise ProcSubmitError("supervisor reported the caller's pid")
        update_meta_field(artifacts_dir, "pid", supervisor.pid)

    def after_ack(proc: Any) -> None:
        resolved_supervisor_pid = supervisor_pid(proc)
        if resolved_supervisor_pid is None:
            raise ProcSubmitError("supervisor did not report a pid")
        update_meta_field(artifacts_dir, "pid", resolved_supervisor_pid)
        if proc.supervisor_id:
            update_meta_field(
                artifacts_dir, "monitor_supervisor_identity", proc.supervisor_id
            )
        claim = claim_monitor_workspace(
            lane_start.project_file,
            lane_start.workspace_num,
            supervisor_pid=resolved_supervisor_pid,
            transfer_from_pid=lane_start.transfer_from_pid,
            artifacts_timestamp=member_timestamp,
            cl_name=lane_start.cl_name,
        )
        claim_holder["claim"] = claim
        claim_holder["pid"] = resolved_supervisor_pid
        if not claim.result.success:
            claim_error = monitor_claim_error(
                lane_start.project_file,
                lane_start.workspace_num,
                claim.result.error,
            )
            raise ProcSubmitError(
                f"could not claim workspace for monitor: {claim_error}"
            )

    tool_run_id: str | None = None
    tool_run_joined = False
    proc_tags: list[str] = []
    proc_env_overlay: dict[str, str] = {}
    join_recorded = False
    if request.join_run_id is not None:
        # Join: no wrapper resolution and no new ToolRun reservation. The
        # proc follows the existing detached run, and the Rust join is
        # recorded atomically after the member exists, before proc submit.
        from sase.tool.handoff import join_tags, worker_env_overlay
        from sase.tool.join_worker import join_worker_argv

        tool_run_id = request.join_run_id
        tool_run_joined = True
        proc_argv = join_worker_argv(tool_run_id)
        proc_tags = list(join_tags(tool_run_id))
        proc_env_overlay = dict(worker_env_overlay())
        update_meta_field(artifacts_dir, "monitor_tool_run_id", tool_run_id)
        update_meta_field(artifacts_dir, "monitor_tool_run_joined", True)
        _record_monitor_join(
            tool_run_id,
            monitor_id,
            artifacts_dir=artifacts_dir,
            bound_completion_ref=bound_completion_ref,
        )
        join_recorded = True
    else:
        proc_argv, unwrapped_reason = resolve_monitor_tool_wrap(
            request.command,
            request.execution_argv,
            request.profile,
            request.cwd,
            get_monitor_tool_wrap(),
        )
        if unwrapped_reason is not None:
            # The proc supervisor appends, so a pre-submit line stays first and
            # the log explains why this monitor runs raw.
            append_monitor_log_bytes(
                log_path, format_unwrapped_log_line(unwrapped_reason).encode("utf-8")
            )
        from sase.tool.handoff import (
            owner_tags,
            worker_argv,
            worker_env_overlay,
        )

        from .tool_handoff import (
            format_reservation_fallback_line,
            maybe_reserve_monitor_tool_run,
        )

        words = monitor_tool_run_words(
            request.command,
            request.execution_argv,
            proc_argv,
            unwrapped_reason,
        )
        handoff = maybe_reserve_monitor_tool_run(
            words,
            cwd=request.cwd,
            monitor_id=monitor_id,
            starter_agent=lane_start.starter_agent,
        )
        if handoff.attempted:
            reservation = handoff.reservation
            if reservation is not None and reservation.reserved:
                # Adopted: the proc runs the claiming worker, never the
                # E1.5 argv, so one semantic run is never recorded twice.
                tool_run_id = reservation.run_id
                proc_argv = worker_argv(tool_run_id)
                proc_tags = list(owner_tags(tool_run_id))
                proc_env_overlay = dict(worker_env_overlay())
                update_meta_field(artifacts_dir, "monitor_tool_run_id", tool_run_id)
            else:
                # Fail-open: keep the E1.5 argv and name the fallback.
                reason = (
                    reservation.error if reservation is not None else None
                ) or "unknown error"
                append_monitor_log_bytes(
                    log_path,
                    format_reservation_fallback_line(reason).encode("utf-8"),
                )
    timer.mark("tool_reservation")
    try:
        proc = submit_proc_request(
            ProcSubmitRequest(
                argv=proc_argv,
                command=(
                    shlex.split(request.command) if request.execution_argv else None
                ),
                label=label,
                cwd=request.cwd,
                env={
                    "SASE_MONITOR_DIAGNOSTICS_DIR": str(diagnostics_dir(artifacts_dir)),
                    MONITOR_ARTIFACTS_ENV: str(artifacts_dir),
                    "SASE_MONITOR_ID": monitor_id,
                    **_tool_run_agent_overlay(lane_start.starter_agent),
                    **proc_env_overlay,
                },
                origin=MONITOR_PROC_ORIGIN,
                proc_id=monitor_id,
                project=request.project_name,
                workspace_num=lane_start.workspace_num,
                cl_name=lane_start.cl_name,
                proc_name=member_name,
                proc_role="proc",
                tags=proc_tags,
                request_fingerprint=request_fingerprint,
                reserved_by=lane_start.starter_agent,
                timeout_seconds=proc_timeout_seconds(request.timeout_seconds),
                idle_timeout_seconds=proc_timeout_seconds(request.idle_timeout_seconds),
                log_path=log_path,
                log_owner=ARTIFACTS_LOG_OWNER,
                artifacts_dir=artifacts_dir,
                workspace_claim={
                    "project_file": lane_start.project_file,
                    "workspace_num": lane_start.workspace_num,
                    "workflow": MONITOR_WORKSPACE_CLAIM_WORKFLOW,
                    "cl_name": lane_start.cl_name,
                },
                followup={
                    "kind": MONITOR_FOLLOWUP_KIND,
                    "next_action": request.next_action,
                    "next_model": request.next_model,
                    "next_output": request.next_output,
                    "tail_lines": request.tail_lines,
                },
            ),
            after_spawn=after_spawn,
            after_ack=after_ack,
        )
    except ProcSubmitError as exc:
        if join_recorded and tool_run_id is not None:
            # The joiner never started: release the join so the detached
            # run is not pinned to a monitor that does not exist.
            _release_monitor_join(tool_run_id, monitor_id)
        elif tool_run_id is not None:
            # The owner never started: the reserved run explains itself
            # instead of lingering in `created`.
            from sase.tool.handoff import settle_launch_failure

            settle_launch_failure(tool_run_id, str(exc))
        claim = claim_holder.get("claim")
        claimed_supervisor_pid = claim_holder.get("pid")
        if (
            claim is not None
            and claim.result.success
            and isinstance(claimed_supervisor_pid, int)
        ):
            undo_monitor_claim(
                lane_start.project_file,
                lane_start.workspace_num,
                supervisor_pid=claimed_supervisor_pid,
                starter_claim=claim.starter_claim,
                cl_name=lane_start.cl_name,
            )
        if bound_completion_ref is not None:
            from sase.finalizers.prepare import rollback_prepared_completion

            rollback_prepared_completion(
                bound_completion_ref,
                monitor_id=monitor_id,
                artifacts_dir=store_lane.caller_artifacts_dir(),
            )
        teardown_failed_member(artifacts_dir, str(exc))
        raise MonitorError(str(exc)) from exc
    timer.mark("spawn_and_ack")

    record = MonitorRecord(
        monitor_id=monitor_id,
        member_agent_name=member_name,
        lane=durable_lane,
        project_name=request.project_name,
        artifacts_dir=artifacts_dir,
        timestamp=member_timestamp,
        command=request.command,
        cwd=request.cwd,
        reason=request.reason,
        label=label,
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
        policy_digest=request.policy_digest if records_enabled else None,
        pid=proc.pid or claim_holder.get("pid"),
        supervisor_identity=proc.supervisor_id,
        request_fingerprint=request_fingerprint,
        output_path=str(log_path),
        tool_run_id=tool_run_id,
        tool_run_joined=tool_run_joined,
    )
    persist_monitor_start_intent_after_ack(
        request,
        record,
        lane_start=lane_start,
        request_fingerprint=request_fingerprint,
        starter_artifacts_dir=starter_artifacts_dir,
        records_enabled=records_enabled,
    )
    timer.mark("persist_intent")
    timer.log(durable_lane)
    timer.write(artifacts_dir)
    return record


__all__ = ["MonitorLaunchContext", "launch_monitor"]
