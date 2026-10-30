"""Internal staged-monitor transaction: persist, adopt, and clean up.

Public ``start_monitor`` stays on the immediate path until activation.
Tests and later phases call these entries directly. Preparation never
submits a proc; launch reconstructs from the frozen payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
from typing import Any
import uuid

from sase.agent.gate_intent import atomic_write_json
from sase.agent.staged_handoff import (
    StagedHandoffError,
    acquire_staging_reservation,
    build_monitor_staged_record,
    discard_staged_handoff,
    read_staged_handoff,
    release_staging_reservation,
    write_staged_handoff,
)
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    staged_monitor_launch_payload_schema_version,
    validate_staged_monitor_launch_payload,
)
from sase.logs._bounded import log_file_lock

from .logs import monitor_log_path
from .models import MonitorError, MonitorRecord
from .request import StartMonitorRequest
from .staged_owner import (
    clear_staged_owner_index,
    launch_payload_path,
    write_staged_owner_index,
)
from .start_claim import preflight_monitor_workspace_claim
from .start_flow import refuse_finalizer_owned_monitor_start
from .start_lane import LaneStart, StartIdentity, resolve_start_identity
from .start_launch import MonitorLaunchContext, launch_monitor
from .start_metadata import read_start_meta
from .start_prepare import PreparedMonitorStart, prepare_monitor_locked
from .start_runtime import monitor_claim_error, teardown_failed_member
from .start_timing import StartTimer
from .store_lane import caller_artifacts_dir, resolve_lane
from .transaction import monitor_lane_lock_path

_CLAIM_CONTEXT_SCHEMA = "sase.monitor.staged_claim_context.v1"
_STAGE_COMMAND = "sase monitor start"


@dataclass(frozen=True)
class StagedMonitorStart:
    """A reconstructible staged member that has not submitted a proc."""

    record: MonitorRecord
    staged_id: str
    payload: dict[str, Any]
    replayed: bool = False


@dataclass(frozen=True)
class StagedMonitorCleanupResult:
    """Outcome of unwinding one unstarted staged monitor."""

    monitor_id: str
    staged_id: str | None
    held: bool
    released_join: bool
    settled_tool_run_id: str | None
    member_state: str
    released_prepared_intent: bool = False
    skipped: bool = False


def load_staged_monitor_launch_payload(artifacts_dir: str) -> dict[str, Any]:
    """Return the validated frozen launch payload for *artifacts_dir*."""
    path = launch_payload_path(artifacts_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MonitorError(f"staged monitor launch payload missing at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError(
            f"staged monitor launch payload unreadable at {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise MonitorError(f"staged monitor launch payload is not an object: {path}")
    try:
        return validate_staged_monitor_launch_payload(raw)
    except StagedHandoffContractError as exc:
        raise MonitorError(f"staged monitor launch payload is invalid: {exc}") from exc


def stage_monitor(
    request: StartMonitorRequest,
    *,
    staged_id: str | None = None,
    reservation_id: str | None = None,
) -> StagedMonitorStart:
    """Persist a staged monitor member without submitting a proc.

    Acquires the one-handoff slot before mutating preparation, then publishes
    through the reservation-aware writer. Identical-request replay returns
    the existing record.
    """
    refuse_finalizer_owned_monitor_start()
    timer = StartTimer()
    identity = resolve_start_identity(request)
    timer.mark("resolve_identity")
    starter_dir = _starter_artifacts_dir(request, identity)
    if not starter_dir:
        raise MonitorError("staged monitor starts require starter artifacts")
    owned_reservation = reservation_id
    acquired_here = False
    if owned_reservation is None:
        try:
            existing = read_staged_handoff(starter_dir)
        except StagedHandoffError as exc:
            raise MonitorError(str(exc)) from exc
        # A live monitor stage already occupies the one-handoff slot.
        # Replay and lane conflict go through prepare without re-acquiring.
        if existing is None or existing.get("kind") != "monitor":
            try:
                owned_reservation = acquire_staging_reservation(
                    artifacts_dir=starter_dir,
                    command=_STAGE_COMMAND,
                )
            except StagedHandoffError as exc:
                raise MonitorError(str(exc)) from exc
            acquired_here = True
    published = False
    try:
        with log_file_lock(
            monitor_lane_lock_path(request.project_name, identity.lock_lane)
        ):
            timer.mark("lane_lock")
            staged, published = _stage_monitor_locked(
                request,
                identity,
                timer,
                staged_id=staged_id,
                reservation_id=owned_reservation,
                starter_dir=starter_dir,
            )
            return staged
    finally:
        if acquired_here and owned_reservation is not None and not published:
            release_staging_reservation(owned_reservation, artifacts_dir=starter_dir)


def launch_from_persisted_payload(artifacts_dir: str) -> MonitorRecord:
    """Launch a staged monitor from its frozen payload under the lane lock."""
    payload = load_staged_monitor_launch_payload(artifacts_dir)
    claim = _claim_context(payload)
    project_name = str(claim.get("project_name") or "")
    lane = str(payload.get("lane") or claim.get("durable_lane") or "")
    if not project_name or not lane:
        raise MonitorError("staged launch payload is missing project or lane")
    timer = StartTimer()
    with log_file_lock(monitor_lane_lock_path(project_name, lane)):
        timer.mark("lane_lock")
        return _launch_from_persisted_payload_locked(
            artifacts_dir, payload, claim, timer
        )


def cleanup_staged_monitor(
    artifacts_dir: str,
    *,
    held: bool = False,
    join_mode: str | None = None,
    tool_run_id: str | None = None,
    staged_id: str | None = None,
    starter_artifacts_dir: str | None = None,
    prepared_intent_ref: str | None = None,
    tool_run_joined: bool = False,
) -> StagedMonitorCleanupResult:
    """Unwind unstarted staged resources. Safe to repeat.

    Settles an owned reserved ToolRun as never executed. Releases only this
    stage's join reservation. Never stops an already-running joined run. A
    held cleanup keeps the outer staged record.
    """
    try:
        meta = read_start_meta(artifacts_dir)
    except (OSError, MonitorError):
        meta = {}
    monitor_id = str(meta.get("monitor_id") or "")
    state = str(meta.get("monitor_state") or "")
    if state == "running":
        return StagedMonitorCleanupResult(
            monitor_id=monitor_id,
            staged_id=staged_id or str(meta.get("monitor_staged_id") or "") or None,
            held=held,
            released_join=False,
            settled_tool_run_id=None,
            member_state=state,
            released_prepared_intent=False,
            skipped=True,
        )
    payload = _load_payload_optional(artifacts_dir)
    claim = _claim_context(payload) if payload is not None else {}
    staged = (
        staged_id
        or str(meta.get("monitor_staged_id") or "")
        or str((payload or {}).get("staged_id") or "")
        or None
    )
    mode = join_mode or str(claim.get("join_mode") or "none")
    run_id = tool_run_id or str(claim.get("tool_run_id") or "") or None
    if run_id is None:
        resources = (payload or {}).get("resources")
        if isinstance(resources, dict):
            raw = resources.get("tool_run_id")
            run_id = str(raw) if raw else None
    joined = tool_run_joined or bool(claim.get("tool_run_joined"))
    released_join = False
    settled_id: str | None = None
    if mode == "staged" and run_id and staged:
        released_join = _release_staged_join(run_id, staged, monitor_id)
    elif run_id and not joined and mode != "ordinary":
        if _settle_unstarted_run(run_id, held=held):
            settled_id = run_id
    if monitor_id:
        clear_staged_owner_index(monitor_id)
    starter = starter_artifacts_dir or str(claim.get("starter_artifacts_dir") or "")
    if not starter and payload is not None:
        starter_block = payload.get("starter")
        if isinstance(starter_block, dict):
            starter = str(starter_block.get("artifacts_dir") or "")
    prepared_ref = prepared_intent_ref or _prepared_intent_ref(payload or {})
    if prepared_ref is None:
        prepared_ref = _optional_str(claim.get("completion_ref"))
    released_prepared = False
    if prepared_ref and staged and monitor_id and starter:
        from sase.finalizers.prepare import rollback_prepared_completion
        from sase.finalizers._prepare_reservations import release_prepared_intent

        # A pre-ack bind is reusable after rollback. Both operations use the
        # persisted starter store, which is also the reservation's owner.
        rollback_prepared_completion(
            prepared_ref,
            monitor_id=monitor_id,
            artifacts_dir=starter,
        )
        try:
            released_prepared = release_prepared_intent(
                prepared_ref,
                staged_id=staged,
                monitor_id=monitor_id,
                artifacts_dir=starter,
            )
        except Exception:  # noqa: BLE001 - cleanup remains best effort.
            released_prepared = False
    if held:
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

        if monitor_id:
            update_meta_field(artifacts_dir, "monitor_stage_held", True)
        return StagedMonitorCleanupResult(
            monitor_id=monitor_id,
            staged_id=staged,
            held=True,
            released_join=released_join,
            settled_tool_run_id=settled_id,
            member_state=state or "staged",
            released_prepared_intent=released_prepared,
        )
    if starter:
        discard_staged_handoff(starter)
    if monitor_id:
        teardown_failed_member(artifacts_dir, "staged monitor discarded")
    return StagedMonitorCleanupResult(
        monitor_id=monitor_id,
        staged_id=staged,
        held=False,
        released_join=released_join,
        settled_tool_run_id=settled_id,
        member_state="failed",
        released_prepared_intent=released_prepared,
    )


def _stage_monitor_locked(
    request: StartMonitorRequest,
    identity: StartIdentity,
    timer: StartTimer,
    *,
    staged_id: str | None,
    reservation_id: str | None,
    starter_dir: str,
) -> tuple[StagedMonitorStart, bool]:
    stage_id = staged_id or str(uuid.uuid4())
    prepared = prepare_monitor_locked(
        request,
        identity,
        timer,
        member_state="staged",
        bind_completion=False,
        staged_id=stage_id,
    )
    if prepared.replayed is not None:
        timer.log(identity.lock_lane)
        replayed_id = stage_id
        try:
            meta = read_start_meta(prepared.replayed.artifacts_dir)
        except (OSError, MonitorError):
            meta = {}
        existing_id = str(meta.get("monitor_staged_id") or "")
        if existing_id:
            replayed_id = existing_id
        return (
            StagedMonitorStart(
                record=prepared.replayed,
                staged_id=replayed_id,
                payload={},
                replayed=True,
            ),
            False,
        )
    context = prepared.context
    if context is None:
        raise MonitorError("monitor preparation produced no launch context")
    prepared_reservation: dict[str, Any] | None = None
    try:
        if request.completion_ref:
            from sase.finalizers._prepare_reservations import (
                reserve_prepared_intent,
            )

            command_argv, _execution_argv = _command_argv(context.request)
            prepared_reservation = {
                "staged_id": stage_id,
                "monitor_id": context.monitor_id,
                "request_fingerprint": context.request_fingerprint,
                "command": command_argv,
            }
            try:
                reserve_prepared_intent(
                    request.completion_ref,
                    prepared_reservation,
                    artifacts_dir=context.starter_artifacts_dir,
                )
            except Exception as exc:
                raise MonitorError(
                    f"could not reserve prepared completion for staged monitor: {exc}"
                ) from exc
        payload = _build_launch_payload(
            prepared,
            context,
            stage_id,
            prepared_reservation=prepared_reservation,
        )
        try:
            normalized = validate_staged_monitor_launch_payload(payload)
        except StagedHandoffContractError as exc:
            raise MonitorError(
                f"could not freeze staged monitor payload: {exc}"
            ) from exc
        path = launch_payload_path(context.artifacts_dir)
        atomic_write_json(path, normalized)
        write_staged_owner_index(
            context.monitor_id,
            staged_id=stage_id,
            artifacts_dir=context.artifacts_dir,
            starter_artifacts_dir=starter_dir,
        )
        carry_allowed = not _prepared_intent_ref(normalized)
        record = build_monitor_staged_record(
            payload=_outer_handoff_payload(normalized),
            staged_id=stage_id,
            carry_allowed=carry_allowed,
        )
        try:
            write_staged_handoff(
                record,
                artifacts_dir=starter_dir,
                command=_STAGE_COMMAND,
                reservation_id=reservation_id,
            )
        except StagedHandoffError as exc:
            raise MonitorError(str(exc)) from exc
    except Exception:
        cleanup_staged_monitor(
            context.artifacts_dir,
            held=False,
            join_mode=context.join_mode,
            tool_run_id=context.reserved_tool_run_id,
            staged_id=context.staged_id,
            starter_artifacts_dir=starter_dir,
            prepared_intent_ref=context.request.completion_ref,
            tool_run_joined=context.tool_run_joined,
        )
        raise
    timer.mark("persist_payload")
    timer.write(context.artifacts_dir)
    return (
        StagedMonitorStart(
            record=_staged_record(context),
            staged_id=stage_id,
            payload=normalized,
        ),
        True,
    )


def _launch_from_persisted_payload_locked(
    artifacts_dir: str,
    payload: dict[str, Any],
    claim: dict[str, Any],
    timer: StartTimer,
) -> MonitorRecord:
    meta = read_start_meta(artifacts_dir)
    if str(meta.get("monitor_state") or "") == "running":
        from .store import read_monitor_marker

        project_name = str(claim.get("project_name") or "")
        existing = read_monitor_marker(project_name, artifacts_dir)
        if existing is not None:
            return existing
    try:
        context = _reconstruct_launch_context(artifacts_dir, payload, claim, meta)
        context = _revalidate_claim(context)
        _revalidate_reserved_run(context)
        context = _bind_staged_prepared_completion(context, payload)
        return launch_monitor(context, timer)
    except Exception:
        # Adoption failure holds the published handoff for recovery. Only an
        # explicit discard may remove that outer record.
        cleanup_staged_monitor(artifacts_dir, held=True)
        raise


def _starter_artifacts_dir(
    request: StartMonitorRequest, identity: StartIdentity
) -> str | None:
    if identity.context is not None:
        return identity.context.record.artifact_dir
    caller = caller_artifacts_dir()
    if caller:
        return caller
    try:
        return resolve_lane(request.project_name, identity.target).record.artifact_dir
    except Exception:  # noqa: BLE001 - missing starter is a staging refusal.
        return None


def _build_launch_payload(
    prepared: PreparedMonitorStart,
    context: MonitorLaunchContext,
    staged_id: str,
    *,
    prepared_reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = context.request
    lane_start = context.lane_start
    command_argv, execution_argv = _command_argv(request)
    starter_dir = context.starter_artifacts_dir or ""
    starter_run_id = (
        request.starter_run_id
        or os.path.basename(str(starter_dir).rstrip("/"))
        or "unknown-starter"
    )
    starter_agent = (lane_start.starter_agent or "").strip() or "sase"
    protocol = prepared.continuation_protocol or "legacy"
    resources: dict[str, Any] = {}
    if context.reserved_tool_run_id:
        resources["tool_run_id"] = context.reserved_tool_run_id
    if request.completion_ref:
        resources["prepared_intent_ref"] = request.completion_ref
    if prepared_reservation is not None:
        resources["prepared_reservation"] = dict(prepared_reservation)
    payload: dict[str, Any] = {
        "schema_version": staged_monitor_launch_payload_schema_version(),
        "staged_id": staged_id,
        "monitor_id": context.monitor_id,
        "member_id": f"{lane_start.durable_lane}{context.suffix}",
        "request_fingerprint": context.request_fingerprint,
        "command": command_argv,
        "execution_argv": execution_argv,
        "label": context.label,
        "policy_digest": _policy_digest_hex(
            prepared.frozen_policy, context.request_fingerprint
        ),
        "lane": lane_start.durable_lane,
        "cwd": request.cwd,
        "starter": {
            "agent_id": starter_agent,
            "run_id": starter_run_id,
            "artifacts_dir": starter_dir,
            "workspace_id": str(lane_start.workspace_num),
        },
        "workspace": {
            "mode": "inherit",
            "claim_context": _claim_context_payload(prepared, context),
        },
        "continuation": {
            "parent_node_ids": list(request.parent_node_ids),
            "protocol": protocol,
        },
        "resources": resources,
    }
    if request.checkpoint_ref:
        payload["continuation"]["checkpoint_ref"] = request.checkpoint_ref
    if prepared.frozen_policy is not None:
        payload["policy"] = dict(prepared.frozen_policy)
    return payload


def _bind_staged_prepared_completion(
    context: MonitorLaunchContext,
    payload: dict[str, Any],
) -> MonitorLaunchContext:
    """Bind the reserved prepared intent immediately before process launch."""

    request = context.request
    resources = payload.get("resources")
    resources = resources if isinstance(resources, dict) else {}
    intent_ref = _optional_str(resources.get("prepared_intent_ref"))
    reservation = resources.get("prepared_reservation")
    if request.completion_ref is None and intent_ref is None and reservation is None:
        return context
    if (
        request.completion_ref is None
        or intent_ref != request.completion_ref
        or not isinstance(reservation, dict)
        or context.staged_id is None
        or context.starter_artifacts_dir is None
    ):
        raise MonitorError("staged prepared completion reservation is incomplete")
    command_argv, _execution_argv = _command_argv(request)
    expected = {
        "staged_id": context.staged_id,
        "monitor_id": context.monitor_id,
        "request_fingerprint": context.request_fingerprint,
        "command": command_argv,
    }
    if reservation != expected:
        raise MonitorError(
            "staged prepared completion reservation does not match the frozen request"
        )
    from sase.finalizers.prepare import bind_prepared_completion
    from sase.finalizers.declaration import FinalizerDeclarationError

    try:
        bind_prepared_completion(
            request.completion_ref,
            monitor_id=context.monitor_id,
            command=command_argv,
            request_fingerprint=context.request_fingerprint,
            staged_id=context.staged_id,
            artifacts_dir=context.starter_artifacts_dir,
        )
    except FinalizerDeclarationError as exc:
        raise MonitorError(str(exc)) from exc
    return replace(context, bound_completion_ref=request.completion_ref)


def _claim_context_payload(
    prepared: PreparedMonitorStart, context: MonitorLaunchContext
) -> dict[str, Any]:
    request = context.request
    lane_start = context.lane_start
    overlay = [[key, value] for key, value in context.proc_env_overlay]
    return {
        "schema": _CLAIM_CONTEXT_SCHEMA,
        "project_name": request.project_name,
        "project_file": lane_start.project_file,
        "workspace_num": lane_start.workspace_num,
        "transfer_from_pid": lane_start.transfer_from_pid,
        "cl_name": lane_start.cl_name,
        "starter_agent": lane_start.starter_agent,
        "starter_provider": context.starter_provider,
        "starter_artifacts_dir": context.starter_artifacts_dir,
        "suffix": context.suffix,
        "durable_lane": lane_start.durable_lane,
        "prev_timestamp": lane_start.prev_timestamp,
        "artifacts_dir": context.artifacts_dir,
        "log_path": str(context.log_path),
        "reason": request.reason,
        "timeout_seconds": request.timeout_seconds,
        "idle_timeout_seconds": request.idle_timeout_seconds,
        "start_status": request.start_status,
        "stop_status": request.stop_status,
        "tail_lines": request.tail_lines,
        "next_action": request.next_action,
        "next_model": request.next_model,
        "next_output": request.next_output,
        "profile": request.profile,
        "join_run_id": request.join_run_id,
        "queue_weight_override": request.queue_weight_override,
        "inherit_lane_workspace_claim": request.inherit_lane_workspace_claim,
        "command": request.command,
        "execution_argv": (
            list(request.execution_argv) if request.execution_argv is not None else None
        ),
        "proc_argv": list(context.proc_argv or ()),
        "proc_tags": list(context.proc_tags),
        "proc_env_overlay": overlay,
        "join_mode": context.join_mode,
        "unwrapped_reason": context.unwrapped_reason,
        "execution_strategy": prepared.execution_strategy,
        "tool_run_joined": context.tool_run_joined,
        "tool_run_id": context.reserved_tool_run_id,
        "completion_ref": request.completion_ref,
        "checkpoint_ref": request.checkpoint_ref,
        "cli_evidence": request.cli_evidence,
    }


def _claim_context(payload: dict[str, Any]) -> dict[str, Any]:
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        return {}
    raw = workspace.get("claim_context")
    return dict(raw) if isinstance(raw, dict) else {}


def _reconstruct_launch_context(
    artifacts_dir: str,
    payload: dict[str, Any],
    claim: dict[str, Any],
    meta: dict[str, Any],
) -> MonitorLaunchContext:
    command = str(claim.get("command") or meta.get("monitor_command") or "")
    if not command:
        argv = payload.get("command") or []
        command = shlex.join(str(part) for part in argv) if argv else ""
    execution_raw = claim.get("execution_argv")
    execution_argv = (
        [str(part) for part in execution_raw]
        if isinstance(execution_raw, list)
        else None
    )
    request = StartMonitorRequest(
        command=command,
        reason=str(claim.get("reason") or meta.get("monitor_reason") or "run command"),
        timeout_seconds=float(
            claim.get("timeout_seconds") or meta.get("monitor_timeout_seconds") or 0
        ),
        cwd=str(payload.get("cwd") or meta.get("monitor_cwd") or ""),
        project_name=str(claim.get("project_name") or ""),
        start_status=str(
            claim.get("start_status")
            or meta.get("monitor_start_status")
            or "MONITORING"
        ),
        stop_status=str(
            claim.get("stop_status") or meta.get("monitor_stop_status") or "MONITORED"
        ),
        lane=str(payload.get("lane") or claim.get("durable_lane") or None),
        label=str(payload.get("label") or ""),
        next_action=_optional_str(claim.get("next_action")),
        next_model=_optional_str(claim.get("next_model")),
        tail_lines=int(
            claim.get("tail_lines") or meta.get("monitor_tail_lines") or 200
        ),
        idle_timeout_seconds=float(claim.get("idle_timeout_seconds") or 0),
        next_output=str(claim.get("next_output") or "auto"),
        inherit_lane_workspace_claim=bool(
            claim.get("inherit_lane_workspace_claim", True)
        ),
        execution_argv=execution_argv,
        completion_ref=_optional_str(claim.get("completion_ref")),
        profile=_optional_str(claim.get("profile")),
        policy_digest=f"sha256:{payload.get('policy_digest')}",
        checkpoint_ref=_optional_str(claim.get("checkpoint_ref")),
        parent_node_ids=tuple(
            str(item)
            for item in (
                (payload.get("continuation") or {}).get("parent_node_ids") or []
            )
            if str(item)
        ),
        starter_run_id=_optional_str((payload.get("starter") or {}).get("run_id")),
        queue_weight_override=(
            float(claim["queue_weight_override"])
            if claim.get("queue_weight_override") is not None
            else None
        ),
        join_run_id=_optional_str(claim.get("join_run_id")),
    )
    overlay_raw = claim.get("proc_env_overlay") or []
    overlay: list[tuple[str, str]] = []
    if isinstance(overlay_raw, list):
        for item in overlay_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                overlay.append((str(item[0]), str(item[1])))
    resources = (
        payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    )
    tool_run_id = _optional_str(claim.get("tool_run_id")) or _optional_str(
        resources.get("tool_run_id") if isinstance(resources, dict) else None
    )
    proc_argv_raw = claim.get("proc_argv") or []
    proc_argv = tuple(str(part) for part in proc_argv_raw) if proc_argv_raw else None
    lane_start = LaneStart(
        project_file=str(claim.get("project_file") or ""),
        member_meta={},
        durable_lane=str(payload.get("lane") or claim.get("durable_lane") or ""),
        cl_name=_optional_str(claim.get("cl_name")),
        prev_timestamp=str(claim.get("prev_timestamp") or ""),
        workspace_num=int(claim.get("workspace_num") or 0),
        transfer_from_pid=(
            int(claim["transfer_from_pid"])
            if claim.get("transfer_from_pid") is not None
            else None
        ),
        starter_agent=_optional_str(claim.get("starter_agent")),
    )
    log_path = monitor_log_path(artifacts_dir)
    raw_log = claim.get("log_path")
    if raw_log:
        log_path = Path(str(raw_log))
    return MonitorLaunchContext(
        request=request,
        lane_start=lane_start,
        label=str(payload.get("label") or ""),
        starter_artifacts_dir=_optional_str(claim.get("starter_artifacts_dir")),
        request_fingerprint=str(payload.get("request_fingerprint") or ""),
        monitor_id=str(payload.get("monitor_id") or meta.get("monitor_id") or ""),
        suffix=str(claim.get("suffix") or ""),
        bound_completion_ref=None,
        artifacts_dir=artifacts_dir,
        log_path=log_path,
        reserved_tool_run_id=tool_run_id,
        tool_run_joined=bool(claim.get("tool_run_joined")),
        proc_argv=proc_argv,
        proc_tags=tuple(str(tag) for tag in (claim.get("proc_tags") or ())),
        proc_env_overlay=tuple(overlay),
        unwrapped_reason=_optional_str(claim.get("unwrapped_reason")),
        join_mode=str(claim.get("join_mode") or "none"),
        member_state="staged",
        staged_id=_optional_str(payload.get("staged_id")),
        starter_provider=_optional_str(claim.get("starter_provider")),
    )


def _revalidate_claim(context: MonitorLaunchContext) -> MonitorLaunchContext:
    lane_start = context.lane_start
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
        return replace(
            context,
            lane_start=replace(
                lane_start, transfer_from_pid=preflight.transfer_from_pid
            ),
        )
    return context


def _revalidate_reserved_run(context: MonitorLaunchContext) -> None:
    if context.join_mode == "staged" or context.tool_run_joined:
        return
    run_id = context.reserved_tool_run_id
    if not run_id:
        return
    from sase.core.tool_run import tool_run_show

    try:
        shown = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - refuse rather than launch blind.
        raise MonitorError(
            f"could not revalidate reserved tool run {run_id}: {exc}"
        ) from exc
    run = shown.get("run") if isinstance(shown, dict) else None
    state = str(run.get("state") or "") if isinstance(run, dict) else ""
    if state and state not in {"created", "running"}:
        raise MonitorError(
            f"reserved tool run {run_id} is {state}; refusing to launch a canceled run"
        )


def _staged_record(context: MonitorLaunchContext) -> MonitorRecord:
    request = context.request
    lane_start = context.lane_start
    return MonitorRecord(
        monitor_id=context.monitor_id,
        member_agent_name=f"{lane_start.durable_lane}{context.suffix}",
        lane=lane_start.durable_lane,
        project_name=request.project_name,
        artifacts_dir=context.artifacts_dir,
        timestamp=os.path.basename(context.artifacts_dir.rstrip("/")),
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
        monitor_state="staged",
        next_action=request.next_action or None,
        next_model=request.next_model or None,
        completion_ref=request.completion_ref or None,
        profile=request.profile or None,
        policy_digest=request.policy_digest,
        pid=None,
        request_fingerprint=context.request_fingerprint,
        output_path=str(context.log_path),
        tool_run_id=context.reserved_tool_run_id,
        tool_run_joined=context.tool_run_joined,
        starter_agent=lane_start.starter_agent,
    )


def _command_argv(request: StartMonitorRequest) -> tuple[list[str], list[str]]:
    command_argv = shlex.split(request.command) or [request.command]
    if request.execution_argv is not None:
        execution_argv = [str(part) for part in request.execution_argv if str(part)]
    else:
        execution_argv = list(command_argv)
    if not execution_argv:
        execution_argv = list(command_argv)
    return command_argv, execution_argv


def _policy_digest_hex(
    frozen_policy: dict[str, Any] | None, request_fingerprint: str
) -> str:
    candidates = []
    if frozen_policy is not None:
        candidates.append(str(frozen_policy.get("fingerprint") or ""))
    candidates.append(request_fingerprint)
    for raw in candidates:
        digest = raw.removeprefix("sha256:")
        if len(digest) == 64 and all(
            char in "0123456789abcdefABCDEF" for char in digest
        ):
            return digest.lower()
    return sha256(b"{}").hexdigest()


def _outer_handoff_payload(launch_payload: dict[str, Any]) -> dict[str, Any]:
    outer = dict(launch_payload)
    intent = _prepared_intent_ref(launch_payload)
    if intent:
        outer["prepared_intent_ref"] = intent
    resources = launch_payload.get("resources")
    if isinstance(resources, dict) and resources.get("prepared_reservation"):
        outer["prepared_reservation"] = resources["prepared_reservation"]
    return outer


def _prepared_intent_ref(payload: dict[str, Any]) -> str | None:
    raw = payload.get("prepared_intent_ref") if isinstance(payload, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw
    resources = payload.get("resources") if isinstance(payload, dict) else None
    if isinstance(resources, dict):
        nested = resources.get("prepared_intent_ref")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def _load_payload_optional(artifacts_dir: str) -> dict[str, Any] | None:
    path = launch_payload_path(artifacts_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _release_staged_join(run_id: str, staged_id: str, monitor_id: str) -> bool:
    from sase.core.tool_run import tool_run_release_staged_join

    try:
        tool_run_release_staged_join(
            {
                "schema_version": 1,
                "run_id": run_id,
                "staged_id": staged_id,
                "monitor_id": monitor_id,
            }
        )
    except Exception:  # noqa: BLE001 - cleanup is best effort and idempotent.
        return False
    return True


def _settle_unstarted_run(run_id: str, *, held: bool) -> bool:
    from sase.tool.executor_recording import finish_tool_run

    reason = (
        "staged monitor held; command was not run"
        if held
        else "staged monitor discarded; command was not run"
    )
    # A reserved run that never started settles as stop_requested.
    return finish_tool_run(
        run_id,
        state="signaled",
        exit_code=None,
        duration_ms=0,
        terminal_cause="stop_requested",
        diagnostics=["command was not run", reason],
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "StagedMonitorCleanupResult",
    "StagedMonitorStart",
    "cleanup_staged_monitor",
    "launch_from_persisted_payload",
    "load_staged_monitor_launch_payload",
    "stage_monitor",
]
