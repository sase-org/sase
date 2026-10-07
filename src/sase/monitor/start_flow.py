"""The monitor-start flow: identity, replay, lane, claim, and member creation.

Split out of :mod:`sase.monitor.start`: this module owns the start *flow* --
lane resolution, the ordered launch transaction up to member creation, and
the teardown each failure point owes before the proc submits. Once the member
exists it hands a :class:`MonitorLaunchContext` to
:func:`sase.monitor.start_launch.launch_monitor`, which owns the proc submit,
the claim moves, and the running record.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.continuation_capture.rollout import (
    monitor_continuation_protocol_for_new_start,
    monitor_continuation_records_enabled,
)
from sase.finalizers.owned_turn import (
    finalizer_owned_turn_is_active,
    finalizer_owned_turn_refusal,
)
from sase.logs._bounded import log_file_lock

from . import naming, store_lane
from .logs import monitor_log_path
from .member import create_monitor_member
from .models import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorRecord,
)
from .request import (
    StartMonitorRequest,
    active_monitor_message,
    default_label,
    monitor_request_fingerprint,
)
from .start_continuation import (
    inherited_route,
    peek_continuation_parents,
    reject_versioned_start_controls_when_disabled,
)
from .start_claim import preflight_monitor_workspace_claim
from .start_lane import (
    StartIdentity,
    resolve_lane_start,
    resolve_start_identity,
)
from .start_launch import MonitorLaunchContext, launch_monitor
from .start_runtime import (
    monitor_claim_error,
    teardown_failed_member,
)
from .start_timing import StartTimer
from .store_lane import LaneMonitorReads
from .transaction import monitor_lane_lock_path


def finalizer_owned_monitor_refusal() -> str:
    """Return the refusal for ``sase monitor start`` in a finalizer turn."""
    return finalizer_owned_turn_refusal(
        "sase monitor start",
        inline_hint=(
            "Re-wait inline with the printed `sase tool wait <run-id>` form, "
            "or run the command in the foreground instead, then finish the "
            "repair in this turn."
        ),
    )


def refuse_finalizer_owned_monitor_start() -> None:
    """Raise before any monitor state exists when a finalizer owns this turn.

    Runs before identity resolution, replay lookup, member creation, proc
    submit, claim moves, and the handoff marker, so a refused start leaves
    no monitor record, proc, transferred claim, or pending handoff behind.
    """
    if finalizer_owned_turn_is_active():
        raise MonitorError(finalizer_owned_monitor_refusal())


def _prepared_completion_accept(
    request: StartMonitorRequest, starter_artifacts_dir: str | None
) -> str | None:
    """Return the sealed accept policy for the bound prepared intent, if any.

    Best effort: when the intent cannot be read (or carries no explicit
    policy), return ``None`` and the frozen policy keeps the default
    pass-only branches.
    """

    if not request.completion_ref or not starter_artifacts_dir:
        return None
    try:
        from sase.finalizers.prepare import load_prepared_completion

        intent = load_prepared_completion(
            request.completion_ref, artifacts_dir=starter_artifacts_dir
        )
    except Exception:  # noqa: BLE001 - freeze must stay pass-only then.
        return None
    accept = intent.get("accept", "pass")
    if accept not in ("pass", "no_new_failures"):
        return None
    return str(accept)


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane.

    An omitted ``request.lane`` is an implicit start: the calling agent
    shell is resolved metadata-first -- its own artifacts dir, then an
    exact ``SASE_AGENT_NAME`` match, then the newest non-monitor member of
    its own agent session -- and the durable agent session is taken from that artifact.
    An explicit lane still resolves to the newest matching agent-session member.
    """
    refuse_finalizer_owned_monitor_start()
    timer = StartTimer()
    identity = resolve_start_identity(request)
    timer.mark("resolve_identity")
    with log_file_lock(
        monitor_lane_lock_path(request.project_name, identity.lock_lane)
    ):
        timer.mark("lane_lock")
        return _start_monitor_locked(request, identity, timer)


def _start_monitor_locked(
    request: StartMonitorRequest, identity: StartIdentity, timer: StartTimer
) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock.

    The lane's monitors are read from the artifact index once, up front, and
    the snapshot is shared by every question this start asks about them.
    """
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
                prepared_completion_accept=_prepared_completion_accept(
                    request, starter_artifacts_dir
                ),
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
    timer.mark("continuation_setup")

    lane_reads = LaneMonitorReads(request.project_name)
    replayed = _replayed_lane_monitor(
        request,
        identity.lock_lane,
        request_fingerprint=request_fingerprint,
        reads=lane_reads,
    )
    timer.mark("replay_lookup")
    if replayed is not None:
        timer.log(identity.lock_lane)
        return replayed

    lane_start = resolve_lane_start(request, identity)
    timer.mark("resolve_lane_start")
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
    timer.mark("claim_preflight")
    durable_lane = lane_start.durable_lane
    suffix = naming.allocate_monitor_suffix(
        durable_lane,
        has_existing_monitor=store_lane.has_any_monitor(
            request.project_name, durable_lane, reads=lane_reads
        ),
    )
    monitor_id = naming.new_monitor_id()
    timer.mark("suffix_lookup")
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
    timer.mark("bind_completion")

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
    timer.mark("create_member")

    return launch_monitor(
        MonitorLaunchContext(
            request=request,
            lane_start=lane_start,
            label=label,
            records_enabled=records_enabled,
            starter_artifacts_dir=starter_artifacts_dir,
            request_fingerprint=request_fingerprint,
            monitor_id=monitor_id,
            suffix=suffix,
            bound_completion_ref=bound_completion_ref,
            artifacts_dir=artifacts_dir,
            log_path=log_path,
        ),
        timer,
    )


def _replayed_lane_monitor(
    request: StartMonitorRequest,
    lane: str,
    *,
    request_fingerprint: str,
    reads: LaneMonitorReads,
) -> MonitorRecord | None:
    """Return the monitor a replayed start should reuse, if there is one.

    Raises when an existing monitor blocks the start; returns ``None`` when
    the lane is clear for a new one -- including a lost monitor from some
    *other* request, which a new start is allowed to supersede.
    """
    existing_record = store_lane.monitor_blocking_start_for_lane(
        request.project_name, lane, reads=reads
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
    "finalizer_owned_monitor_refusal",
    "refuse_finalizer_owned_monitor_start",
    "start_monitor",
]
