"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch.

This module owns the start *flow* -- lane resolution, the ordered launch
transaction, and the teardown each failure point owes -- and re-exports the
names its callers have always imported from here. The pieces it drives live
next door: :mod:`sase.monitor.request` (the request and its identity),
:mod:`sase.monitor.proc_adapter` (the proc-service facade),
:mod:`sase.monitor.start_lane` (lane and workspace resolution),
:mod:`sase.monitor.start_claim` (RUNNING-field claim moves),
:mod:`sase.monitor.start_continuation` (continuation-record setup),
:mod:`sase.monitor.start_runtime` (proc/claim failure helpers), and
:mod:`sase.monitor.handoff` (giving the lane to the monitor from inside an agent).
"""

from __future__ import annotations

import os
import shlex
from dataclasses import replace
from typing import Any

from sase.continuation_capture.rollout import (
    monitor_continuation_protocol_for_new_start,
    monitor_continuation_records_enabled,
)
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.bead.epic_launch_handoff import MONITOR_ARTIFACTS_ENV
from sase.logs._bounded import log_file_lock
from sase.procs.models import ARTIFACTS_LOG_OWNER
from sase.procs.request import ProcSubmitRequest
from sase.procs.submission import ProcSubmitError, submit_proc_request
from sase.procs.spawn import SUPERVISOR_LOG_NAME, DetachedSupervisor

from . import naming, store_lane
from .claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from .diagnostics import diagnostics_dir
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
from .start_continuation import (
    inherited_route,
    peek_continuation_parents,
    persist_monitor_start_intent_after_ack,
    reject_versioned_start_controls_when_disabled,
)
from .start_claim import (
    claim_monitor_workspace,
    preflight_monitor_workspace_claim,
    undo_monitor_claim,
)
from .start_lane import (
    StartIdentity,
    resolve_lane_start,
    resolve_start_identity,
)
from .start_runtime import (
    monitor_claim_error,
    proc_timeout_seconds,
    supervisor_pid,
    teardown_failed_member,
)
from .transaction import (
    MONITOR_GO_MARKER,
    monitor_lane_lock_path,
)


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane.

    An omitted ``request.lane`` is an implicit start: the calling agent
    shell is resolved metadata-first -- its own artifacts dir, then an
    exact ``SASE_AGENT_NAME`` match, then the newest non-monitor member of
    its own family -- and the durable family is taken from that artifact.
    An explicit lane still resolves to the newest matching family member.
    """
    identity = resolve_start_identity(request)
    with log_file_lock(
        monitor_lane_lock_path(request.project_name, identity.lock_lane)
    ):
        return _start_monitor_locked(request, identity)


def _start_monitor_locked(
    request: StartMonitorRequest, identity: StartIdentity
) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock."""
    label = request.label or default_label(request.command)
    records_enabled = monitor_continuation_records_enabled()
    continuation_protocol = monitor_continuation_protocol_for_new_start(records_enabled)
    if not records_enabled:
        reject_versioned_start_controls_when_disabled(request)
        parent_node_ids: list[str] = []
        starter_run_id = None
        starter_artifacts_dir = None
    else:
        parent_node_ids, starter_run_id, starter_artifacts_dir = (
            peek_continuation_parents(request, identity)
        )
    request = replace(
        request,
        parent_node_ids=tuple(parent_node_ids),
        starter_run_id=starter_run_id,
    )
    frozen_policy: dict[str, Any] | None = None
    if records_enabled:
        inherited_model, inherited_effort = inherited_route(starter_artifacts_dir)
        try:
            from sase.monitor.outcome_policy import freeze_start_outcome_policy

            frozen_policy = freeze_start_outcome_policy(
                request,
                inherited_model=inherited_model,
                inherited_effort=inherited_effort,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise MonitorError(str(exc)) from exc
    if frozen_policy is not None:
        request = replace(
            request,
            policy_digest=str(frozen_policy.get("fingerprint") or "") or None,
        )
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

    lane_start = resolve_lane_start(request, identity)
    preflight = preflight_monitor_workspace_claim(
        lane_start.project_file,
        lane_start.workspace_num,
        transfer_from_pid=lane_start.transfer_from_pid,
        cl_name=lane_start.cl_name,
    )
    if preflight.error is not None:
        claim_error = monitor_claim_error(
            lane_start.project_file,
            lane_start.workspace_num,
            preflight.error,
        )
        raise MonitorError(f"could not claim workspace for monitor: {claim_error}")
    if preflight.transfer_from_pid != lane_start.transfer_from_pid:
        lane_start = replace(
            lane_start,
            transfer_from_pid=preflight.transfer_from_pid,
        )
    durable_lane = lane_start.durable_lane
    suffix = naming.allocate_monitor_suffix(
        durable_lane,
        has_existing_monitor=store_lane.has_any_monitor(
            request.project_name, durable_lane
        ),
    )
    monitor_id = naming.new_monitor_id()
    bound_completion_ref: str | None = None
    if request.completion_ref:
        from sase.finalizers.declaration import FinalizerDeclarationError
        from sase.finalizers.prepare import bind_prepared_completion

        starter_artifacts = store_lane.caller_artifacts_dir()
        try:
            bind_prepared_completion(
                request.completion_ref,
                monitor_id=monitor_id,
                command=request.command,
                request_fingerprint=request_fingerprint,
                artifacts_dir=starter_artifacts,
            )
        except FinalizerDeclarationError as exc:
            raise MonitorError(str(exc)) from exc
        bound_completion_ref = request.completion_ref

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
        completion_ref=request.completion_ref if records_enabled else None,
        profile=request.profile if records_enabled else None,
        policy_digest=request.policy_digest if records_enabled else None,
        checkpoint_ref=request.checkpoint_ref if records_enabled else None,
        starter_artifacts_dir=starter_artifacts_dir if records_enabled else None,
        parent_node_ids=request.parent_node_ids if records_enabled else (),
        continuation_protocol=continuation_protocol,
        queue_weight_override=request.queue_weight_override,
    )
    log_path = monitor_log_path(artifacts_dir)
    update_meta_field(artifacts_dir, "monitor_output_path", str(log_path))
    if frozen_policy is not None:
        try:
            from sase.continuation_capture import persist_frozen_outcome_policy

            persist_frozen_outcome_policy(artifacts_dir, frozen_policy)
        except Exception as exc:
            if bound_completion_ref is not None:
                from sase.finalizers.prepare import rollback_prepared_completion

                rollback_prepared_completion(
                    bound_completion_ref,
                    monitor_id=monitor_id,
                    artifacts_dir=store_lane.caller_artifacts_dir(),
                )
            teardown_failed_member(artifacts_dir, str(exc))
            raise MonitorError(
                f"could not persist frozen outcome policy: {exc}"
            ) from exc
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
                env={
                    "SASE_MONITOR_DIAGNOSTICS_DIR": str(diagnostics_dir(artifacts_dir)),
                    MONITOR_ARTIFACTS_ENV: str(artifacts_dir),
                    "SASE_MONITOR_ID": monitor_id,
                },
                origin=MONITOR_PROC_ORIGIN,
                proc_id=monitor_id,
                project=request.project_name,
                workspace_num=lane_start.workspace_num,
                cl_name=lane_start.cl_name,
                shell_name=member_name,
                shell_kind="proc",
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
    )
    persist_monitor_start_intent_after_ack(
        request,
        record,
        lane_start=lane_start,
        request_fingerprint=request_fingerprint,
        starter_artifacts_dir=starter_artifacts_dir,
        records_enabled=records_enabled,
    )
    return record


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
    existing_record = store_lane.monitor_blocking_start_for_lane(
        request.project_name, lane
    )
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
