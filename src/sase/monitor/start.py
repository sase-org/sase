"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch.

This module owns the start *flow* -- lane resolution, the ordered launch
transaction, and the teardown each failure point owes -- and re-exports the
names its callers have always imported from here. The pieces it drives live
next door: :mod:`sase.monitor.request` (the request and its identity),
:mod:`sase.monitor.spawn` (the supervisor process), :mod:`sase.monitor
.start_claim` (RUNNING-field claim moves), and :mod:`sase.monitor.handoff`
(giving the lane to the monitor from inside an agent).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.logs._bounded import log_file_lock
from sase.plan_chain import agent_family_base
from sase.workflows.utils import get_project_file_path

from . import naming, store
from .claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from .followup_prompt import DEFAULT_NEXT_OUTPUT, NEXT_OUTPUT_CHOICES
from .handoff import (
    MONITOR_PENDING_MARKER,
    maybe_handoff_monitor_from_agent,
    will_handoff_monitor_to_agent_runner,
    write_monitor_pending_marker,
)
from .identity import process_identity
from .member import create_monitor_member
from .models import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorLaneError,
    MonitorRecord,
)
from .request import (
    DEFAULT_START_STATUS,
    DEFAULT_STOP_STATUS,
    DEFAULT_TAIL_LINES,
    StartMonitorRequest,
    active_monitor_message,
    default_label,
    monitor_request_fingerprint,
)
from .settlement import finalize_monitor_workflow_state, project_name_from_artifacts_dir
from .spawn import (
    SUPERVISOR_LOG_NAME,
    DetachedSupervisor,
    SupervisorSpawnError,
    spawn_detached_supervisor,
    terminate_supervisor,
    wait_for_start_acknowledgement,
)
from .start_claim import (
    claim_monitor_workspace,
    release_monitor_claim,
    undo_monitor_claim,
)
from .transaction import (
    MONITOR_GO_MARKER,
    monitor_go_path,
    monitor_lane_lock_path,
    write_json_marker_atomic,
)


@dataclass(frozen=True)
class _LaneStart:
    """The lane state a start resolves before it creates anything.

    ``workspace_num``/``transfer_from_pid`` carry the workspace-inheritance
    decision: a monitor started from the lane's own workspace takes that
    workspace over from the starter's runner, and one started anywhere else
    runs workspace-less (``0``) with a fresh claim.
    """

    project_file: str
    raw_meta: dict[str, Any]
    durable_lane: str
    cl_name: str | None
    prev_timestamp: str
    workspace_num: int
    transfer_from_pid: int | None
    starter_agent: str | None


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane."""
    lane = request.lane or store.default_lane()
    if not lane:
        raise MonitorLaneError(
            "no lane given and SASE_AGENT_NAME is unset; pass an explicit lane"
        )

    with log_file_lock(monitor_lane_lock_path(request.project_name, lane)):
        return _start_monitor_locked(request, lane)


def _start_monitor_locked(request: StartMonitorRequest, lane: str) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock."""
    label = request.label or default_label(request.command)
    request_fingerprint = monitor_request_fingerprint(request, lane=lane, label=label)

    replayed = _replayed_lane_monitor(
        request,
        lane,
        request_fingerprint=request_fingerprint,
    )
    if replayed is not None:
        return replayed

    lane_start = _resolve_lane_start(request, lane)
    durable_lane = lane_start.durable_lane
    suffix = naming.allocate_monitor_suffix(
        durable_lane,
        has_existing_monitor=store.has_any_monitor(request.project_name, durable_lane),
    )
    monitor_id = naming.new_monitor_id()

    artifacts_dir = create_monitor_member(
        request.project_name,
        lane_start.raw_meta,
        lane=durable_lane,
        suffix=suffix,
        prev_artifacts_timestamp=lane_start.prev_timestamp,
        workspace_num=lane_start.workspace_num,
        monitor_id=monitor_id,
        command=request.command,
        cwd=request.cwd,
        label=label,
        reason=request.reason,
        next_action=request.next_action,
        start_status=request.start_status,
        stop_status=request.stop_status,
        timeout_seconds=request.timeout_seconds,
        tail_lines=request.tail_lines,
        idle_timeout_seconds=request.idle_timeout_seconds,
        next_output=request.next_output,
        request_fingerprint=request_fingerprint,
        starter_agent=lane_start.starter_agent,
    )

    supervisor = _launch_supervisor(artifacts_dir)
    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))

    claim = claim_monitor_workspace(
        lane_start.project_file,
        lane_start.workspace_num,
        supervisor_pid=supervisor.pid,
        transfer_from_pid=lane_start.transfer_from_pid,
        artifacts_timestamp=member_timestamp,
        cl_name=lane_start.cl_name,
    )
    if not claim.result.success:
        terminate_supervisor(supervisor)
        _teardown_failed_member(
            artifacts_dir, f"could not claim workspace: {claim.result.error}"
        )
        raise MonitorError(
            f"could not claim workspace for monitor: {claim.result.error}"
        )

    try:
        _write_monitor_go_marker(
            artifacts_dir,
            monitor_id=monitor_id,
            request_fingerprint=request_fingerprint,
        )
    except OSError as exc:
        terminate_supervisor(supervisor)
        release_monitor_claim(
            lane_start.project_file,
            lane_start.workspace_num,
            cl_name=lane_start.cl_name,
        )
        _teardown_failed_member(
            artifacts_dir, f"could not release monitor launch barrier: {exc}"
        )
        raise MonitorError(f"could not release monitor launch barrier: {exc}") from exc

    ack_error = wait_for_start_acknowledgement(artifacts_dir, supervisor)
    if ack_error is not None:
        terminate_supervisor(supervisor)
        undo_monitor_claim(
            lane_start.project_file,
            lane_start.workspace_num,
            supervisor_pid=supervisor.pid,
            starter_claim=claim.starter_claim,
            cl_name=lane_start.cl_name,
        )
        _teardown_failed_member(artifacts_dir, ack_error)
        raise MonitorError(ack_error)

    return MonitorRecord(
        monitor_id=monitor_id,
        member_agent_name=f"{durable_lane}{suffix}",
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
        pid=supervisor.pid,
        supervisor_identity=supervisor.identity,
        request_fingerprint=request_fingerprint,
    )


def _replayed_lane_monitor(
    request: StartMonitorRequest,
    lane: str,
    *,
    request_fingerprint: str,
) -> MonitorRecord | None:
    """Return the monitor a replayed start should reuse, if there is one.

    Raises when an existing monitor blocks the start; returns ``None`` when
    the lane is clear for a new one -- including a lost monitor from some
    *other* request, which a new start is allowed to supersede.
    """
    existing_record = store.monitor_blocking_start_for_lane(request.project_name, lane)
    if existing_record is None:
        return None

    if existing_record.monitor_state == "lost":
        if existing_record.request_fingerprint == request_fingerprint:
            short_id = naming.short_monitor_id(existing_record.monitor_id)
            raise MonitorAlreadyRunningError(
                f"lane {lane!r} has lost monitor {existing_record.monitor_id}; "
                f"inspect it with `sase monitor show {short_id} --all-lines` "
                "before replaying the same monitor request"
            )
        return None

    if existing_record.request_fingerprint == request_fingerprint:
        return existing_record

    raise MonitorAlreadyRunningError(
        active_monitor_message(
            lane,
            existing_record,
            requested_fingerprint=request_fingerprint,
            requested_command=request.command,
        )
    )


def _resolve_lane_start(request: StartMonitorRequest, lane: str) -> _LaneStart:
    """Read the lane's newest member and decide what the monitor inherits."""
    lane_ctx = store.resolve_lane(request.project_name, lane)
    newest = lane_ctx.record
    raw_meta = _read_meta(newest.artifact_dir)

    durable_lane = str(raw_meta.get("agent_family") or "")
    if not durable_lane:
        from sase.agent._family_promotion import promote_agent_to_family

        promoted_name = promote_agent_to_family(newest.artifact_dir, lane)
        durable_lane = agent_family_base(promoted_name) or lane
        raw_meta = _read_meta(newest.artifact_dir)

    workspace_dir = raw_meta.get("workspace_dir")
    raw_lane_workspace_num = raw_meta.get("workspace_num")
    raw_runner_pid = raw_meta.get("pid")
    lane_workspace_num = (
        int(raw_lane_workspace_num) if raw_lane_workspace_num is not None else None
    )
    runner_pid = int(raw_runner_pid) if raw_runner_pid is not None else None
    cwd_matches_lane = bool(workspace_dir) and _same_path(
        request.cwd, str(workspace_dir)
    )

    transfer_from_pid: int | None = None
    starter_agent: str | None = None
    if (
        request.inherit_lane_workspace_claim
        and cwd_matches_lane
        and lane_workspace_num is not None
        and runner_pid is not None
    ):
        resolved_workspace_num = lane_workspace_num
        transfer_from_pid = runner_pid
        raw_name = raw_meta.get("name")
        starter_agent = raw_name if isinstance(raw_name, str) and raw_name else None
    else:
        resolved_workspace_num = 0

    cl_name = raw_meta.get("cl_name")
    return _LaneStart(
        project_file=newest.project_file,
        raw_meta=raw_meta,
        durable_lane=durable_lane,
        cl_name=cl_name if isinstance(cl_name, str) else None,
        prev_timestamp=newest.timestamp,
        workspace_num=resolved_workspace_num,
        transfer_from_pid=transfer_from_pid,
        starter_agent=starter_agent,
    )


def _launch_supervisor(artifacts_dir: str) -> DetachedSupervisor:
    """Spawn the detached supervisor and record how to identify it."""
    try:
        supervisor = spawn_detached_supervisor(artifacts_dir)
    except (OSError, ValueError, SupervisorSpawnError) as exc:
        _teardown_failed_member(
            artifacts_dir, f"could not start monitor supervisor: {exc}"
        )
        raise MonitorError(f"could not start monitor supervisor: {exc}") from exc

    # Write the pid before its identity: a crash between these two calls
    # still leaves a pid a caller can signal, and the identity is the
    # stronger of the two, not a substitute. The launch barrier below holds
    # the command behind the claim without reordering this pair.
    update_meta_field(artifacts_dir, "pid", supervisor.pid)
    supervisor_identity = process_identity(supervisor.pid)
    update_meta_field(artifacts_dir, "monitor_supervisor_identity", supervisor_identity)
    return DetachedSupervisor(supervisor.pid, supervisor_identity)


def _write_monitor_go_marker(
    artifacts_dir: str,
    *,
    monitor_id: str,
    request_fingerprint: str,
) -> None:
    write_json_marker_atomic(
        monitor_go_path(artifacts_dir),
        {
            "monitor_id": monitor_id,
            "request_fingerprint": request_fingerprint,
            "timestamp": time.time(),
        },
    )


def _teardown_failed_member(artifacts_dir: str, error: str) -> None:
    """Mark a half-created monitor member failed rather than phantom-running."""
    meta = _read_meta(artifacts_dir)
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
    }
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_monitor_workflow_state(artifacts_dir)


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return left == right


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MonitorError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


__all__ = [
    "DEFAULT_NEXT_OUTPUT",
    "DEFAULT_START_STATUS",
    "DEFAULT_STOP_STATUS",
    "DEFAULT_TAIL_LINES",
    "MONITOR_GO_MARKER",
    "MONITOR_PENDING_MARKER",
    "MONITOR_WORKSPACE_CLAIM_WORKFLOW",
    "NEXT_OUTPUT_CHOICES",
    "SUPERVISOR_LOG_NAME",
    "StartMonitorRequest",
    "maybe_handoff_monitor_from_agent",
    "start_monitor",
    "will_handoff_monitor_to_agent_runner",
    "write_monitor_pending_marker",
]
