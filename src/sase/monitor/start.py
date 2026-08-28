"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch.

This module owns the start *flow* -- lane resolution, the ordered launch
transaction, and the teardown each failure point owes -- and re-exports the
names its callers have always imported from here. The pieces it drives live
next door: :mod:`sase.monitor.request` (the request and its identity),
:mod:`sase.monitor.proc_adapter` (the proc-service facade),
:mod:`sase.monitor.start_claim` (RUNNING-field claim moves), and
:mod:`sase.monitor.handoff` (giving the lane to the monitor from inside an
agent).
"""

from __future__ import annotations

import json
import os
import shlex
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
from sase.monitor_state import monitor_state_bucket
from sase.plan_chain import agent_family_base
from sase.procs.models import ARTIFACTS_LOG_OWNER
from sase.procs.request import ProcSubmitRequest
from sase.procs.runtime import proc_started_path, read_json_object
from sase.procs.service import ProcSubmitError, submit_proc_request
from sase.procs.spawn import SUPERVISOR_LOG_NAME, DetachedSupervisor
from sase.running_field import get_claimed_workspaces
from sase.workspace_provider import resolve_workspace_num_for_dir
from sase.workspace_provider.utils import parse_workspace_dir
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
from .logs import monitor_log_path
from .member import create_monitor_member
from .models import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorLaneError,
    MonitorRecord,
)
from .proc_adapter import (
    MONITOR_FOLLOWUP_KIND,
    MONITOR_PROC_ORIGIN,
    compile_monitor_argv,
    monitor_proc_argv,
)
from .request import (
    DEFAULT_REASON,
    DEFAULT_START_STATUS,
    DEFAULT_STOP_STATUS,
    DEFAULT_TAIL_LINES,
    DEFAULT_TIMEOUT_SECONDS,
    StartMonitorRequest,
    active_monitor_message,
    default_label,
    monitor_request_fingerprint,
)
from .settlement import finalize_monitor_workflow_state, project_name_from_artifacts_dir
from .start_claim import (
    claim_monitor_workspace,
    undo_monitor_claim,
)
from .transaction import (
    MONITOR_GO_MARKER,
    monitor_lane_lock_path,
)


@dataclass(frozen=True)
class _LaneStart:
    """The lane state a start resolves before it creates anything.

    ``workspace_num`` is the workspace identity for the directory the monitored
    command runs in. ``transfer_from_pid`` is set only when that identity is the
    starter runner's own live claim row and should move to the supervisor.
    """

    project_file: str
    member_meta: dict[str, Any]
    durable_lane: str
    cl_name: str | None
    prev_timestamp: str
    workspace_num: int
    transfer_from_pid: int | None
    starter_agent: str | None


@dataclass(frozen=True)
class _StartIdentity:
    """How a start chose its parent artifact and durable family lane.

    ``target`` is the resolved parent's own agent name for an implicit
    start, or the explicit ``--agent`` / lane string. ``context`` is the
    already-resolved artifact for an implicit start, reused by
    ``_resolve_lane_start()`` instead of re-resolving; it is ``None`` for
    an explicit start, which still resolves via ``store.resolve_lane()``.
    ``lock_lane`` is the durable family used for the start lock, replay,
    conflict detection, and request fingerprint.
    """

    target: str
    context: store.LaneContext | None
    lock_lane: str


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane.

    An omitted ``request.lane`` is an implicit start: the calling agent
    shell is resolved metadata-first -- its own artifacts dir, then an
    exact ``SASE_AGENT_NAME`` match, then the newest non-monitor member of
    its own family -- and the durable family is taken from that artifact.
    An explicit lane still resolves to the newest matching family member.
    """
    identity = _resolve_start_identity(request)
    with log_file_lock(
        monitor_lane_lock_path(request.project_name, identity.lock_lane)
    ):
        return _start_monitor_locked(request, identity)


def _resolve_start_identity(request: StartMonitorRequest) -> _StartIdentity:
    """Return the parent identity and durable lock lane for *request*."""
    if request.lane:
        return _StartIdentity(target=request.lane, context=None, lock_lane=request.lane)
    caller = store.default_caller()
    if not caller:
        raise MonitorLaneError(
            "no lane given and SASE_AGENT_NAME is unset; pass an explicit lane"
        )
    ctx = store.resolve_caller_agent(
        request.project_name, caller, artifacts_dir=store.caller_artifacts_dir()
    )
    meta = ctx.record.agent_meta
    target = meta.name if meta is not None and meta.name else caller
    lock_lane = store.durable_lane_for_record(ctx.record, fallback=target)
    return _StartIdentity(target=target, context=ctx, lock_lane=lock_lane)


def _start_monitor_locked(
    request: StartMonitorRequest, identity: _StartIdentity
) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock."""
    label = request.label or default_label(request.command)
    request_fingerprint = monitor_request_fingerprint(
        request, lane=identity.lock_lane, label=label
    )

    replayed = _replayed_lane_monitor(
        request,
        identity.lock_lane,
        request_fingerprint=request_fingerprint,
    )
    if replayed is not None:
        return replayed

    lane_start = _resolve_lane_start(request, identity)
    durable_lane = lane_start.durable_lane
    suffix = naming.allocate_monitor_suffix(
        durable_lane,
        has_existing_monitor=store.has_any_monitor(request.project_name, durable_lane),
    )
    monitor_id = naming.new_monitor_id()

    artifacts_dir = create_monitor_member(
        request.project_name,
        lane_start.member_meta,
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
        next_model=request.next_model,
        start_status=request.start_status,
        stop_status=request.stop_status,
        timeout_seconds=request.timeout_seconds,
        tail_lines=request.tail_lines,
        idle_timeout_seconds=request.idle_timeout_seconds,
        next_output=request.next_output,
        request_fingerprint=request_fingerprint,
        starter_agent=lane_start.starter_agent,
        execution_argv=request.execution_argv,
    )
    log_path = monitor_log_path(artifacts_dir)
    update_meta_field(artifacts_dir, "monitor_output_path", str(log_path))
    member_name = f"{durable_lane}{suffix}"
    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    claim_holder: dict[str, Any] = {}

    def after_spawn(supervisor: DetachedSupervisor) -> None:
        if supervisor.pid == os.getpid():
            raise ProcSubmitError("supervisor reported the caller's pid")
        update_meta_field(artifacts_dir, "pid", supervisor.pid)

    def after_ack(proc: Any) -> None:
        supervisor_pid = _supervisor_pid(proc)
        if supervisor_pid is None:
            raise ProcSubmitError("supervisor did not report a pid")
        update_meta_field(artifacts_dir, "pid", supervisor_pid)
        if proc.supervisor_id:
            update_meta_field(
                artifacts_dir, "monitor_supervisor_identity", proc.supervisor_id
            )
        claim = claim_monitor_workspace(
            lane_start.project_file,
            lane_start.workspace_num,
            supervisor_pid=supervisor_pid,
            transfer_from_pid=lane_start.transfer_from_pid,
            artifacts_timestamp=member_timestamp,
            cl_name=lane_start.cl_name,
        )
        claim_holder["claim"] = claim
        claim_holder["pid"] = supervisor_pid
        if not claim.result.success:
            claim_error = _monitor_claim_error(
                lane_start.project_file,
                lane_start.workspace_num,
                claim.result.error,
            )
            raise ProcSubmitError(
                f"could not claim workspace for monitor: {claim_error}"
            )

    try:
        proc = submit_proc_request(
            ProcSubmitRequest(
                argv=(
                    monitor_proc_argv(
                        request.command,
                        execution_argv=request.execution_argv,
                    )
                    if request.execution_argv
                    else compile_monitor_argv(request.command)
                ),
                command=(
                    shlex.split(request.command) if request.execution_argv else None
                ),
                label=label,
                cwd=request.cwd,
                origin=MONITOR_PROC_ORIGIN,
                proc_id=monitor_id,
                project=request.project_name,
                workspace_num=lane_start.workspace_num,
                cl_name=lane_start.cl_name,
                shell_name=member_name,
                shell_kind="proc",
                request_fingerprint=request_fingerprint,
                reserved_by=lane_start.starter_agent,
                timeout_seconds=_proc_timeout_seconds(request.timeout_seconds),
                idle_timeout_seconds=_proc_timeout_seconds(
                    request.idle_timeout_seconds
                ),
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
        claim = claim_holder.get("claim")
        supervisor_pid = claim_holder.get("pid")
        if (
            claim is not None
            and claim.result.success
            and isinstance(supervisor_pid, int)
        ):
            undo_monitor_claim(
                lane_start.project_file,
                lane_start.workspace_num,
                supervisor_pid=supervisor_pid,
                starter_claim=claim.starter_claim,
                cl_name=lane_start.cl_name,
            )
        _teardown_failed_member(artifacts_dir, str(exc))
        raise MonitorError(str(exc)) from exc

    return MonitorRecord(
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
        pid=proc.pid or claim_holder.get("pid"),
        supervisor_identity=proc.supervisor_id,
        request_fingerprint=request_fingerprint,
        output_path=str(log_path),
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


def _resolve_lane_start(
    request: StartMonitorRequest, identity: _StartIdentity
) -> _LaneStart:
    """Read the selected parent artifact and decide what the monitor inherits."""
    lane_ctx = (
        identity.context
        if identity.context is not None
        else store.resolve_lane(request.project_name, identity.target)
    )
    selected = lane_ctx.record
    raw_meta = _read_meta(selected.artifact_dir)

    durable_lane = str(raw_meta.get("agent_family") or "").strip()
    if not durable_lane:
        from sase.agent._family_promotion import promote_agent_to_family

        promoted_name = promote_agent_to_family(selected.artifact_dir, identity.target)
        durable_lane = agent_family_base(promoted_name) or identity.target
        raw_meta = _read_meta(selected.artifact_dir)

    workspace_dir = raw_meta.get("workspace_dir")
    raw_lane_workspace_num = raw_meta.get("workspace_num")
    raw_runner_pid = raw_meta.get("pid")
    lane_workspace_num = _optional_int(raw_lane_workspace_num)
    runner_pid = _optional_int(raw_runner_pid)
    cwd_matches_lane = bool(workspace_dir) and _same_path(
        request.cwd, str(workspace_dir)
    )

    resolved_workspace_num = _resolve_monitor_workspace_num(
        selected.project_file,
        request.cwd,
        cwd_matches_lane=cwd_matches_lane,
        lane_workspace_num=lane_workspace_num,
    )
    transfer_from_pid: int | None = None
    starter_agent: str | None = None
    if request.transfer_claim_from_pid is not None:
        transfer_from_pid = request.transfer_claim_from_pid
    elif (
        request.inherit_lane_workspace_claim
        and cwd_matches_lane
        and resolved_workspace_num != 0
        and runner_pid is not None
    ):
        transfer_from_pid = runner_pid
        raw_name = raw_meta.get("name")
        starter_agent = raw_name if isinstance(raw_name, str) and raw_name else None

    member_meta = dict(raw_meta)
    member_meta["workspace_dir"] = request.cwd
    member_meta["workspace_num"] = resolved_workspace_num

    cl_name = raw_meta.get("cl_name")
    return _LaneStart(
        project_file=selected.project_file,
        member_meta=member_meta,
        durable_lane=durable_lane,
        cl_name=cl_name if isinstance(cl_name, str) else None,
        prev_timestamp=selected.timestamp,
        workspace_num=resolved_workspace_num,
        transfer_from_pid=transfer_from_pid,
        starter_agent=starter_agent,
    )


def _resolve_monitor_workspace_num(
    project_file: str,
    cwd: str,
    *,
    cwd_matches_lane: bool,
    lane_workspace_num: int | None,
) -> int:
    """Return the workspace number that owns the monitor command's cwd."""
    if cwd_matches_lane and lane_workspace_num not in (None, 0):
        return lane_workspace_num

    cwd_workspace_num = _lookup_workspace_num_for_dir(project_file, cwd)
    if cwd_workspace_num is not None:
        return cwd_workspace_num

    if cwd_matches_lane and lane_workspace_num is not None:
        return lane_workspace_num

    return 0


def _lookup_workspace_num_for_dir(project_file: str, directory: str) -> int | None:
    primary_workspace_dir = parse_workspace_dir(project_file)
    if not primary_workspace_dir:
        return None
    return resolve_workspace_num_for_dir(primary_workspace_dir, directory)


def _supervisor_pid(proc: Any) -> int | None:
    """Return the supervisor pid from the proc row or its start acknowledgement."""
    if isinstance(proc.pid, int):
        return proc.pid
    started = read_json_object(proc_started_path(proc.proc_id))
    raw = started.get("pid")
    return raw if isinstance(raw, int) else None


def _proc_timeout_seconds(value: float) -> int | None:
    """Convert a monitor timeout to the integer seconds the proc wire stores."""
    if value <= 0:
        return None
    return max(1, int(round(value)))


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
        "status_bucket": monitor_state_bucket("failed"),
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


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _monitor_claim_error(
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


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MonitorError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


__all__ = [
    "DEFAULT_NEXT_OUTPUT",
    "DEFAULT_REASON",
    "DEFAULT_START_STATUS",
    "DEFAULT_STOP_STATUS",
    "DEFAULT_TAIL_LINES",
    "DEFAULT_TIMEOUT_SECONDS",
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
