"""Persist a staged monitor member without submitting a proc.

Stage path of the internal staged-monitor transaction split from
:mod:`sase.monitor.start_stage`. Acquires the one-handoff slot before
mutating preparation, then publishes through the reservation-aware writer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import os
from typing import Any
import uuid

from sase.agent.gate_intent import atomic_write_json
from sase.agent.staged_handoff import (
    StagedHandoffError,
    acquire_staging_reservation,
    build_monitor_staged_record,
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

from ._start_stage_shared import command_argv, prepared_intent_ref
from .models import MonitorError, MonitorRecord
from .request import StartMonitorRequest
from .staged_owner import launch_payload_path, write_staged_owner_index
from .start_flow import refuse_finalizer_owned_monitor_start
from .start_lane import StartIdentity, resolve_start_identity
from .start_launch import MonitorLaunchContext
from .start_metadata import read_start_meta
from .start_prepare import PreparedMonitorStart, prepare_monitor_locked
from .start_stage_cleanup import cleanup_staged_monitor
from .start_timing import StartTimer
from .store_lane import caller_artifacts_dir, resolve_lane
from .transaction import monitor_lane_lock_path

_CLAIM_CONTEXT_SCHEMA = "sase.monitor.staged_claim_context.v1"
_STAGE_COMMAND = "sase monitor start"


@dataclass(frozen=True)
class _StagedMonitorStart:
    """A reconstructible staged member that has not submitted a proc."""

    record: MonitorRecord
    staged_id: str
    payload: dict[str, Any]
    replayed: bool = False


def stage_monitor(
    request: StartMonitorRequest,
    *,
    staged_id: str | None = None,
    reservation_id: str | None = None,
) -> _StagedMonitorStart:
    """Persist a staged monitor member without submitting a proc.

    Acquires the one-handoff slot before mutating preparation, then publishes
    through the reservation-aware writer. Identical-request replay returns
    the existing record.
    """
    refuse_finalizer_owned_monitor_start()
    request = _canonicalize_authored_checkpoint_request(request)
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


def _stage_monitor_locked(
    request: StartMonitorRequest,
    identity: StartIdentity,
    timer: StartTimer,
    *,
    staged_id: str | None,
    reservation_id: str | None,
    starter_dir: str,
) -> tuple[_StagedMonitorStart, bool]:
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
            _StagedMonitorStart(
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

            command_parts, _execution_parts = command_argv(context.request)
            prepared_reservation = {
                "staged_id": stage_id,
                "monitor_id": context.monitor_id,
                "request_fingerprint": context.request_fingerprint,
                "command": command_parts,
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
        checkpoint_content_ref = _persist_staged_authored_checkpoint(context)
        payload = _build_launch_payload(
            prepared,
            context,
            stage_id,
            prepared_reservation=prepared_reservation,
            checkpoint_content_ref=checkpoint_content_ref,
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
        carry_allowed = not prepared_intent_ref(normalized)
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
        _StagedMonitorStart(
            record=_staged_record(context),
            staged_id=stage_id,
            payload=normalized,
        ),
        True,
    )


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


def _canonicalize_authored_checkpoint_request(
    request: StartMonitorRequest,
) -> StartMonitorRequest:
    document = request.checkpoint_document
    if document is None:
        return request
    from sase.continuation_capture import (
        AuthoredCheckpointError,
        canonicalize_authored_checkpoint,
    )

    try:
        authored = canonicalize_authored_checkpoint(document)
    except AuthoredCheckpointError as exc:
        raise MonitorError(
            f"invalid authored checkpoint for staged monitor: {exc}"
        ) from exc
    if request.checkpoint_ref and request.checkpoint_ref != authored.content_ref:
        raise MonitorError(
            "authored checkpoint content does not match its checkpoint reference"
        )
    return replace(
        request,
        checkpoint_ref=authored.content_ref,
        checkpoint_document=authored.payload,
    )


def _persist_staged_authored_checkpoint(
    context: MonitorLaunchContext,
) -> str | None:
    document = context.request.checkpoint_document
    if document is None:
        return None
    from sase.continuation_capture import (
        AuthoredCheckpointError,
        canonicalize_authored_checkpoint,
        persist_authored_checkpoint,
    )

    try:
        authored = canonicalize_authored_checkpoint(document)
        if context.request.checkpoint_ref != authored.content_ref:
            raise MonitorError(
                "authored checkpoint content does not match its checkpoint reference"
            )
        return persist_authored_checkpoint(context.artifacts_dir, authored)
    except AuthoredCheckpointError as exc:
        raise MonitorError(
            f"could not persist authored checkpoint for staged monitor: {exc}"
        ) from exc


def _build_launch_payload(
    prepared: PreparedMonitorStart,
    context: MonitorLaunchContext,
    staged_id: str,
    *,
    prepared_reservation: dict[str, Any] | None = None,
    checkpoint_content_ref: str | None = None,
) -> dict[str, Any]:
    request = context.request
    lane_start = context.lane_start
    command_parts, execution_parts = command_argv(request)
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
        "command": command_parts,
        "execution_argv": execution_parts,
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
    claim_context_block = payload["workspace"]["claim_context"]
    if request.checkpoint_document is not None:
        claim_context_block["checkpoint_content_required"] = True
    if checkpoint_content_ref is not None:
        claim_context_block["checkpoint_content_ref"] = checkpoint_content_ref
    if request.checkpoint_ref:
        payload["continuation"]["checkpoint_ref"] = request.checkpoint_ref
    if prepared.frozen_policy is not None:
        payload["policy"] = dict(prepared.frozen_policy)
    return payload


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
        "join_starter_agent": lane_start.join_starter_agent,
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
    intent = prepared_intent_ref(launch_payload)
    if intent:
        outer["prepared_intent_ref"] = intent
    resources = launch_payload.get("resources")
    if isinstance(resources, dict) and resources.get("prepared_reservation"):
        outer["prepared_reservation"] = resources["prepared_reservation"]
    return outer


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


__all__ = [
    "stage_monitor",
]
