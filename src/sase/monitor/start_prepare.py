"""Shared monitor-start preparation: identity, member, and ToolRun reservation.

Both the immediate ``start_monitor`` facade and the internal staging entry
run this under the lane lock. Preparation never submits a proc, writes
``.go``, moves a claim, or publishes a start-intent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.config._settings import get_monitor_tool_wrap
from sase.continuation_capture.rollout import (
    monitor_continuation_protocol_for_new_start,
)

from . import naming, store_lane
from .logs import append_monitor_log_bytes, monitor_log_path
from .member import create_monitor_member
from .models import MonitorAlreadyRunningError, MonitorError, MonitorRecord
from .request import (
    StartMonitorRequest,
    active_monitor_message,
    default_label,
    monitor_request_fingerprint,
)
from .start_claim import preflight_monitor_workspace_claim
from .start_continuation import inherited_route, peek_continuation_parents
from .start_lane import LaneStart, StartIdentity, resolve_lane_start
from .start_launch import MonitorLaunchContext
from .start_runtime import monitor_claim_error, teardown_failed_member
from .start_timing import StartTimer
from .store_lane import LaneMonitorReads
from .tool_wrap import (
    format_unwrapped_log_line,
    monitor_tool_run_words,
    resolve_monitor_tool_wrap,
)

JoinMode = Literal["none", "ordinary", "staged"]
ExecutionStrategy = Literal["join", "reserved", "wrapped", "raw"]


@dataclass(frozen=True)
class PreparedMonitorStart:
    """Outcome of one locked preparation: a replay or a launch context."""

    replayed: MonitorRecord | None = None
    context: MonitorLaunchContext | None = None
    frozen_policy: dict[str, Any] | None = None
    continuation_protocol: str | None = None
    execution_strategy: ExecutionStrategy = "raw"
    unwrapped_reason: str | None = None


def _replayed_lane_monitor(
    request: StartMonitorRequest,
    lane: str,
    *,
    request_fingerprint: str,
    reads: LaneMonitorReads,
) -> MonitorRecord | None:
    """Return the monitor a replayed start should reuse, if there is one."""
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


def _prepared_completion_accept(
    request: StartMonitorRequest, starter_artifacts_dir: str | None
) -> str | None:
    """Return the sealed accept policy for the bound prepared intent, if any."""
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


def _bind_prepared_completion(
    request: StartMonitorRequest,
    *,
    monitor_id: str,
    request_fingerprint: str,
) -> str | None:
    """Bind a prepared intent for an immediate start, or return ``None``."""
    if not request.completion_ref:
        return None
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
    return request.completion_ref


def _reserve_join_or_tool_run(
    request: StartMonitorRequest,
    *,
    lane_start: LaneStart,
    monitor_id: str,
    artifacts_dir: str,
    log_path: Path,
    staged_id: str | None,
    bound_completion_ref: str | None,
) -> tuple[
    list[str],
    str | None,
    bool,
    list[str],
    dict[str, str],
    JoinMode,
    ExecutionStrategy,
    str | None,
]:
    """Reserve a join or ordinary ToolRun; never submit a proc."""
    from sase.tool.handoff import (
        join_tags,
        owner_tags,
        worker_argv,
        worker_env_overlay,
    )

    from .tool_handoff import (
        format_reservation_fallback_line,
        maybe_reserve_monitor_tool_run,
    )

    if request.join_run_id is not None:
        from sase.tool.join_worker import join_worker_argv

        tool_run_id = request.join_run_id
        proc_argv = join_worker_argv(tool_run_id)
        proc_tags = list(join_tags(tool_run_id))
        proc_env_overlay = dict(worker_env_overlay())
        update_meta_field(artifacts_dir, "monitor_tool_run_id", tool_run_id)
        update_meta_field(artifacts_dir, "monitor_tool_run_joined", True)
        if staged_id is not None:
            _reserve_staged_join(
                tool_run_id,
                staged_id=staged_id,
                monitor_id=monitor_id,
                agent=lane_start.starter_agent,
                artifacts_dir=artifacts_dir,
                bound_completion_ref=bound_completion_ref,
            )
            return (
                proc_argv,
                tool_run_id,
                True,
                proc_tags,
                proc_env_overlay,
                "staged",
                "join",
                None,
            )
        return (
            proc_argv,
            tool_run_id,
            True,
            proc_tags,
            proc_env_overlay,
            "ordinary",
            "join",
            None,
        )

    proc_argv, unwrapped_reason = resolve_monitor_tool_wrap(
        request.command,
        request.execution_argv,
        request.profile,
        request.cwd,
        get_monitor_tool_wrap(),
    )
    if unwrapped_reason is not None:
        append_monitor_log_bytes(
            log_path, format_unwrapped_log_line(unwrapped_reason).encode("utf-8")
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
    if not handoff.attempted:
        strategy: ExecutionStrategy = "raw" if unwrapped_reason else "wrapped"
        return proc_argv, None, False, [], {}, "none", strategy, unwrapped_reason
    reservation = handoff.reservation
    if reservation is not None and reservation.reserved:
        tool_run_id = reservation.run_id
        proc_argv = worker_argv(tool_run_id)
        proc_tags = list(owner_tags(tool_run_id))
        proc_env_overlay = dict(worker_env_overlay())
        update_meta_field(artifacts_dir, "monitor_tool_run_id", tool_run_id)
        return (
            proc_argv,
            tool_run_id,
            False,
            proc_tags,
            proc_env_overlay,
            "none",
            "reserved",
            unwrapped_reason,
        )
    reason = (reservation.error if reservation is not None else None) or "unknown error"
    append_monitor_log_bytes(
        log_path, format_reservation_fallback_line(reason).encode("utf-8")
    )
    return proc_argv, None, False, [], {}, "none", "wrapped", unwrapped_reason


def _reserve_staged_join(
    run_id: str,
    *,
    staged_id: str,
    monitor_id: str,
    agent: str | None,
    artifacts_dir: str,
    bound_completion_ref: str | None,
) -> None:
    """Reserve an existing ToolRun for this staged monitor, or roll back."""
    from sase.core.tool_run import tool_run_reserve_staged_join

    from .join import show_pointer

    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "staged_id": staged_id,
        "monitor_id": monitor_id,
        "agent": (agent or "").strip() or "sase",
    }
    try:
        result = tool_run_reserve_staged_join(request)
    except Exception as exc:  # noqa: BLE001 - a failed reserve starts no monitor.
        _teardown_prepare_failure(
            artifacts_dir, bound_completion_ref, monitor_id, str(exc)
        )
        raise MonitorError(
            f"could not reserve join for tool run {run_id} ({exc}); "
            f"no monitor started ({show_pointer(run_id)})"
        ) from exc
    if not isinstance(result, dict) or result.get("outcome") != "reserved":
        refusal = (
            str(result.get("refusal") or "refused")
            if isinstance(result, dict)
            else "refused"
        )
        message = (
            f"tool run {run_id} cannot be reserved for staged join "
            f"({refusal}); no monitor started ({show_pointer(run_id)})"
        )
        _teardown_prepare_failure(
            artifacts_dir, bound_completion_ref, monitor_id, message
        )
        raise MonitorError(message)


def _teardown_prepare_failure(
    artifacts_dir: str,
    bound_completion_ref: str | None,
    monitor_id: str,
    message: str,
) -> None:
    if bound_completion_ref is not None:
        from sase.finalizers.prepare import rollback_prepared_completion

        rollback_prepared_completion(
            bound_completion_ref,
            monitor_id=monitor_id,
            artifacts_dir=store_lane.caller_artifacts_dir(),
        )
    teardown_failed_member(artifacts_dir, message)


def prepare_monitor_locked(
    request: StartMonitorRequest,
    identity: StartIdentity,
    timer: StartTimer,
    *,
    member_state: str = "running",
    bind_completion: bool = True,
    staged_id: str | None = None,
) -> PreparedMonitorStart:
    """Prepare one monitor while the caller holds the lane start lock.

    Creates the member and reserves any ordinary ToolRun or staged join.
    Does not submit a proc or move a workspace claim.
    """
    label = request.label or default_label(request.command)
    continuation_protocol = monitor_continuation_protocol_for_new_start()
    parent_node_ids, starter_run_id, starter_artifacts_dir = peek_continuation_parents(
        request, identity
    )
    request = replace(
        request,
        parent_node_ids=tuple(parent_node_ids),
        starter_run_id=starter_run_id,
    )
    inherited_model, inherited_effort = inherited_route(starter_artifacts_dir)
    frozen_policy: dict[str, Any] | None = None
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
        return PreparedMonitorStart(replayed=replayed)

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
    if bind_completion:
        bound_completion_ref = _bind_prepared_completion(
            request,
            monitor_id=monitor_id,
            request_fingerprint=request_fingerprint,
        )
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
        completion_ref=request.completion_ref,
        profile=request.profile,
        policy_digest=request.policy_digest,
        checkpoint_ref=request.checkpoint_ref,
        starter_artifacts_dir=starter_artifacts_dir,
        parent_node_ids=request.parent_node_ids,
        continuation_protocol=continuation_protocol,
        queue_weight_override=request.queue_weight_override,
        monitor_state=member_state,
        staged_id=staged_id,
    )
    log_path = monitor_log_path(artifacts_dir)
    update_meta_field(artifacts_dir, "monitor_output_path", str(log_path))
    if frozen_policy is not None:
        try:
            from sase.continuation_capture import persist_frozen_outcome_policy

            persist_frozen_outcome_policy(artifacts_dir, frozen_policy)
        except Exception as exc:
            _teardown_prepare_failure(
                artifacts_dir, bound_completion_ref, monitor_id, str(exc)
            )
            raise MonitorError(
                f"could not persist frozen outcome policy: {exc}"
            ) from exc
    timer.mark("create_member")

    try:
        (
            proc_argv,
            tool_run_id,
            tool_run_joined,
            proc_tags,
            proc_env_overlay,
            join_mode,
            strategy,
            unwrapped_reason,
        ) = _reserve_join_or_tool_run(
            request,
            lane_start=lane_start,
            monitor_id=monitor_id,
            artifacts_dir=artifacts_dir,
            log_path=log_path,
            staged_id=staged_id,
            bound_completion_ref=bound_completion_ref,
        )
    except MonitorError:
        raise
    except Exception as exc:
        _teardown_prepare_failure(
            artifacts_dir, bound_completion_ref, monitor_id, str(exc)
        )
        raise MonitorError(str(exc)) from exc
    timer.mark("tool_reservation")

    starter_provider: str | None = None
    try:
        from sase.agent.identity import discover_agent_runtime

        starter_provider = discover_agent_runtime()
    except Exception:  # noqa: BLE001 - provider attribution is best effort.
        starter_provider = None

    context = MonitorLaunchContext(
        request=request,
        lane_start=lane_start,
        label=label,
        starter_artifacts_dir=starter_artifacts_dir,
        request_fingerprint=request_fingerprint,
        monitor_id=monitor_id,
        suffix=suffix,
        bound_completion_ref=bound_completion_ref,
        artifacts_dir=artifacts_dir,
        log_path=log_path,
        reserved_tool_run_id=tool_run_id,
        tool_run_joined=tool_run_joined,
        proc_argv=tuple(proc_argv),
        proc_tags=tuple(proc_tags),
        proc_env_overlay=tuple(proc_env_overlay.items()),
        unwrapped_reason=unwrapped_reason,
        join_mode=join_mode,
        member_state=member_state,
        staged_id=staged_id,
        starter_provider=starter_provider,
    )
    return PreparedMonitorStart(
        context=context,
        frozen_policy=frozen_policy,
        continuation_protocol=continuation_protocol,
        execution_strategy=strategy,
        unwrapped_reason=unwrapped_reason,
    )


__all__ = [
    "ExecutionStrategy",
    "JoinMode",
    "PreparedMonitorStart",
    "prepare_monitor_locked",
]
