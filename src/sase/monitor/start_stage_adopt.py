"""Adopt a staged monitor member from its frozen payload.

Adoption path of the internal staged-monitor transaction split from
:mod:`sase.monitor.start_stage`. Reconstructs the launch context under the
lane lock, revalidates the workspace claim and reserved run, binds any
reserved prepared completion, then submits the proc.

When the member state was never flipped to running (or the outer receipt
was never written), a retry must not submit a second proc: an existing
proc row for the frozen monitor id is adopted instead, whether it is
still active or already terminal. A held cleanup that settled the
reserved run or released the prepared reservation is repaired by
reacquiring the same logical reservation under the lane lock; a canceled
run is never reused and an ambiguous command is never restarted.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
from typing import Any

from sase.agent.gate_intent import atomic_write_json
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    validate_staged_monitor_launch_payload,
)
from sase.logs._bounded import log_file_lock

from ._start_stage_shared import claim_context, command_argv, optional_str
from .logs import monitor_log_path
from .models import MonitorError, MonitorRecord
from .request import StartMonitorRequest
from .staged_owner import launch_payload_path
from .start_claim import preflight_monitor_workspace_claim
from .start_lane import LaneStart
from .start_launch import MonitorLaunchContext, launch_monitor
from .start_metadata import read_start_meta
from .start_runtime import monitor_claim_error
from .start_stage_cleanup import cleanup_staged_monitor
from .start_timing import StartTimer
from .transaction import monitor_lane_lock_path


def launch_from_persisted_payload(
    artifacts_dir: str,
    *,
    starter_continuation_node_id: str | None = None,
) -> MonitorRecord:
    """Launch a staged monitor from its frozen payload under the lane lock."""
    payload = _load_staged_monitor_launch_payload(artifacts_dir)
    claim = claim_context(payload)
    project_name = str(claim.get("project_name") or "")
    lane = str(payload.get("lane") or claim.get("durable_lane") or "")
    if not project_name or not lane:
        raise MonitorError("staged launch payload is missing project or lane")
    timer = StartTimer()
    with log_file_lock(monitor_lane_lock_path(project_name, lane)):
        timer.mark("lane_lock")
        if starter_continuation_node_id is not None:
            if not starter_continuation_node_id.strip():
                raise MonitorError("starter continuation node id must not be empty")
            continuation = payload.get("continuation")
            if not isinstance(continuation, dict):
                raise MonitorError("staged monitor continuation payload is malformed")
            continuation["parent_node_ids"] = [starter_continuation_node_id]
            try:
                payload = validate_staged_monitor_launch_payload(payload)
            except StagedHandoffContractError as exc:
                raise MonitorError(
                    f"could not bind starter continuation parent: {exc}"
                ) from exc
            atomic_write_json(launch_payload_path(artifacts_dir), payload)
        return _launch_from_persisted_payload_locked(
            artifacts_dir, payload, claim, timer
        )


def _load_staged_monitor_launch_payload(artifacts_dir: str) -> dict[str, Any]:
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
        recovered = _adopt_existing_proc(artifacts_dir, payload, claim, meta, timer)
        if recovered is not None:
            return recovered
        context = _reconstruct_launch_context(artifacts_dir, payload, claim, meta)
        context = _revalidate_claim(context)
        context = _reacquire_settled_tool_run(context)
        _revalidate_reserved_run(context)
        context = _bind_staged_prepared_completion(context, payload)
        return launch_monitor(context, timer)
    except Exception:
        # Adoption failure holds the published handoff for recovery. Only an
        # explicit discard may remove that outer record.
        cleanup_staged_monitor(artifacts_dir, held=True)
        raise


def _adopt_existing_proc(
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

    context = _reconstruct_launch_context(artifacts_dir, payload, claim, meta)
    if str(proc.status or "") not in TERMINAL_PROC_STATUSES:
        if proc.pid is None:
            raise MonitorError(
                f"adopted proc for staged monitor {context.monitor_id!r} "
                "has no supervisor pid; refusing to move the workspace claim"
            )
        context = _ensure_adopt_workspace_claim(context, proc.pid)
        context = _bind_staged_prepared_completion(context, payload)
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
    context = _revalidate_claim(context)
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


def _load_staged_authored_checkpoint(
    artifacts_dir: str,
    claim: dict[str, Any],
) -> dict[str, object] | None:
    required = claim.get("checkpoint_content_required", False)
    if not isinstance(required, bool):
        raise MonitorError("staged authored checkpoint requirement is malformed")
    raw_ref = claim.get("checkpoint_content_ref")
    if raw_ref is None:
        if required:
            raise MonitorError(
                "staged authored checkpoint content reference is missing"
            )
        return None
    if not isinstance(raw_ref, str) or not raw_ref.startswith("local:"):
        raise MonitorError("staged authored checkpoint content reference is invalid")

    relative = Path(raw_ref.removeprefix("local:"))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("continuation", "checkpoints")
    ):
        raise MonitorError("staged authored checkpoint content reference is unsafe")
    root = Path(artifacts_dir).resolve(strict=False)
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MonitorError(
            "staged authored checkpoint content escapes its monitor"
        ) from exc
    try:
        raw_document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MonitorError(
            f"staged authored checkpoint content is missing or corrupt: {exc}"
        ) from exc
    if not isinstance(raw_document, dict):
        raise MonitorError("staged authored checkpoint content is not an object")

    from sase.continuation_capture import (
        AuthoredCheckpointError,
        canonicalize_authored_checkpoint,
    )

    try:
        authored = canonicalize_authored_checkpoint(raw_document)
    except AuthoredCheckpointError as exc:
        raise MonitorError(
            f"staged authored checkpoint content is invalid: {exc}"
        ) from exc
    expected_ref = claim.get("checkpoint_ref")
    if not isinstance(expected_ref, str) or expected_ref != authored.content_ref:
        raise MonitorError(
            "staged authored checkpoint content does not match its frozen digest"
        )
    expected_filename = f"authored-{authored.digest[:16]}.json"
    if raw_document != authored.payload or path.name != expected_filename:
        raise MonitorError(
            "staged authored checkpoint content does not match its frozen digest"
        )
    return authored.payload


def _bind_staged_prepared_completion(
    context: MonitorLaunchContext,
    payload: dict[str, Any],
) -> MonitorLaunchContext:
    """Bind the reserved prepared intent immediately before process launch."""

    request = context.request
    resources = payload.get("resources")
    resources = resources if isinstance(resources, dict) else {}
    intent_ref = optional_str(resources.get("prepared_intent_ref"))
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
    command_parts, _execution_parts = command_argv(request)
    expected = {
        "staged_id": context.staged_id,
        "monitor_id": context.monitor_id,
        "request_fingerprint": context.request_fingerprint,
        "command": command_parts,
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
            command=command_parts,
            request_fingerprint=context.request_fingerprint,
            staged_id=context.staged_id,
            artifacts_dir=context.starter_artifacts_dir,
        )
    except FinalizerDeclarationError as exc:
        _retain_or_restore_prepared_binding(context, reservation, command_parts, exc)
    return replace(context, bound_completion_ref=request.completion_ref)


def _retain_or_restore_prepared_binding(
    context: MonitorLaunchContext,
    reservation: dict[str, Any],
    command_parts: list[str],
    bind_error: Exception,
) -> None:
    """Retain or reacquire the prepared binding after a failed bind.

    A crash after binding but before proc submit leaves the intent
    bound to this monitor: retaining it preserves the prepared
    evidence. A held cleanup rolls the intent back and releases the
    reservation: re-reserving the identical frozen reservation restores
    it for the retry. Anything else (a stolen intent, a consumed
    intent, a mismatched binding) is a precise refusal.
    """
    from sase.finalizers._prepare_reservations import reserve_prepared_intent
    from sase.finalizers.declaration import FinalizerDeclarationError
    from sase.finalizers.prepare import (
        bind_prepared_completion,
        load_prepared_completion,
    )

    starter = context.starter_artifacts_dir
    assert starter is not None
    try:
        intent = load_prepared_completion(
            str(context.request.completion_ref), artifacts_dir=starter
        )
    except FinalizerDeclarationError as exc:
        raise MonitorError(str(exc)) from exc
    binding = intent.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    if (
        str(intent.get("status") or "") == "bound"
        and str(binding.get("monitor_id") or "") == context.monitor_id
        and str(binding.get("request_fingerprint") or "") == context.request_fingerprint
        and list(binding.get("bound_command") or []) == command_parts
    ):
        return
    if str(intent.get("status") or "") != "prepared":
        raise MonitorError(str(bind_error)) from bind_error
    try:
        reserve_prepared_intent(
            str(context.request.completion_ref),
            dict(reservation),
            artifacts_dir=starter,
        )
        bind_prepared_completion(
            str(context.request.completion_ref),
            monitor_id=context.monitor_id,
            command=command_parts,
            request_fingerprint=context.request_fingerprint,
            staged_id=context.staged_id,
            artifacts_dir=starter,
        )
    except FinalizerDeclarationError as exc:
        raise MonitorError(str(exc)) from exc


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
    checkpoint_document = _load_staged_authored_checkpoint(artifacts_dir, claim)
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
        next_action=optional_str(claim.get("next_action")),
        next_model=optional_str(claim.get("next_model")),
        tail_lines=int(
            claim.get("tail_lines") or meta.get("monitor_tail_lines") or 200
        ),
        idle_timeout_seconds=float(claim.get("idle_timeout_seconds") or 0),
        next_output=str(claim.get("next_output") or "auto"),
        inherit_lane_workspace_claim=bool(
            claim.get("inherit_lane_workspace_claim", True)
        ),
        execution_argv=execution_argv,
        completion_ref=optional_str(claim.get("completion_ref")),
        profile=optional_str(claim.get("profile")),
        policy_digest=f"sha256:{payload.get('policy_digest')}",
        checkpoint_ref=optional_str(claim.get("checkpoint_ref")),
        checkpoint_document=checkpoint_document,
        parent_node_ids=tuple(
            str(item)
            for item in (
                (payload.get("continuation") or {}).get("parent_node_ids") or []
            )
            if str(item)
        ),
        starter_run_id=optional_str((payload.get("starter") or {}).get("run_id")),
        queue_weight_override=(
            float(claim["queue_weight_override"])
            if claim.get("queue_weight_override") is not None
            else None
        ),
        join_run_id=optional_str(claim.get("join_run_id")),
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
    tool_run_id = optional_str(claim.get("tool_run_id")) or optional_str(
        resources.get("tool_run_id") if isinstance(resources, dict) else None
    )
    proc_argv_raw = claim.get("proc_argv") or []
    proc_argv = tuple(str(part) for part in proc_argv_raw) if proc_argv_raw else None
    lane_start = LaneStart(
        project_file=str(claim.get("project_file") or ""),
        member_meta={},
        durable_lane=str(payload.get("lane") or claim.get("durable_lane") or ""),
        cl_name=optional_str(claim.get("cl_name")),
        prev_timestamp=str(claim.get("prev_timestamp") or ""),
        workspace_num=int(claim.get("workspace_num") or 0),
        transfer_from_pid=(
            int(claim["transfer_from_pid"])
            if claim.get("transfer_from_pid") is not None
            else None
        ),
        starter_agent=optional_str(claim.get("starter_agent")),
        join_starter_agent=optional_str(claim.get("join_starter_agent")),
    )
    log_path = monitor_log_path(artifacts_dir)
    raw_log = claim.get("log_path")
    if raw_log:
        log_path = Path(str(raw_log))
    return MonitorLaunchContext(
        request=request,
        lane_start=lane_start,
        label=str(payload.get("label") or ""),
        starter_artifacts_dir=optional_str(claim.get("starter_artifacts_dir")),
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
        unwrapped_reason=optional_str(claim.get("unwrapped_reason")),
        join_mode=str(claim.get("join_mode") or "none"),
        member_state="staged",
        staged_id=optional_str(payload.get("staged_id")),
        starter_provider=optional_str(claim.get("starter_provider")),
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


#: Evidence a reserved run never executed its command.
_NEVER_RAN_MARKER = "command was not run"
#: Settlement left by an explicit discard; a discarded stage never resurrects.
_DISCARD_MARKER = "staged monitor discarded; command was not run"


def _reacquire_settled_tool_run(
    context: MonitorLaunchContext,
) -> MonitorLaunchContext:
    """Replace a held-settled reservation with a fresh run for the retry.

    A failed launch settles the reserved run as never-executed so the
    retry must not reuse the canceled run. When the settlement proves
    the command never ran, the stage is still live, and no proc was
    ever submitted for this monitor, reserve a fresh ToolRun for the
    same frozen command under the lane lock. Anything else (a live
    reservation, a join, a discard, or an unproven settlement) is left
    for :func:`_revalidate_reserved_run` to refuse precisely.
    """
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    if context.join_mode != "none" or context.tool_run_joined:
        return context
    run_id = context.reserved_tool_run_id
    if not run_id or context.staged_id is None:
        return context
    shown = _show_reserved_run(context.monitor_id, run_id)
    run = shown.get("run") if isinstance(shown, dict) else None
    if not isinstance(run, dict):
        return context
    state = str(run.get("state") or "")
    if not state or state in {"created", "running"}:
        return context
    diagnostics = run.get("diagnostics")
    entries = (
        [str(entry) for entry in diagnostics] if isinstance(diagnostics, list) else []
    )
    if not any(_NEVER_RAN_MARKER in entry for entry in entries):
        return context
    if any(_DISCARD_MARKER in entry for entry in entries):
        return context
    if not _staged_record_still_live(context):
        return context
    from sase.tool.handoff import owner_tags, worker_argv, worker_env_overlay

    fresh_run_id = _reserve_retry_tool_run(context)
    update_meta_field(context.artifacts_dir, "monitor_tool_run_id", fresh_run_id)
    return replace(
        context,
        reserved_tool_run_id=fresh_run_id,
        proc_argv=tuple(worker_argv(fresh_run_id)),
        proc_tags=tuple(owner_tags(fresh_run_id)),
        proc_env_overlay=tuple(sorted(worker_env_overlay().items())),
    )


def _staged_record_still_live(context: MonitorLaunchContext) -> bool:
    """Return whether the originating stage still owns this recovery.

    An explicit discard removes the outer staged record: a retry must
    never reacquire a reservation for a stage that no longer exists. A
    held failure keeps the record, so the retry may proceed. Malformed
    state fails closed toward refusal.
    """
    starter = context.starter_artifacts_dir
    if not starter:
        return False
    try:
        from sase.agent.staged_handoff import read_staged_handoff

        record = read_staged_handoff(starter)
    except Exception:  # noqa: BLE001 - malformed state fails closed.
        return False
    return isinstance(record, dict) and record.get("staged_id") == context.staged_id


def _show_reserved_run(monitor_id: str, run_id: str) -> dict[str, Any]:
    from sase.core.tool_run import tool_run_show

    try:
        return dict(tool_run_show(run_id))
    except Exception as exc:
        raise MonitorError(
            f"could not revalidate reserved tool run {run_id} for staged "
            f"monitor {monitor_id!r}: {exc}"
        ) from exc


def _reserve_retry_tool_run(context: MonitorLaunchContext) -> str:
    """Reserve a fresh ToolRun for the same frozen monitor command."""
    from sase.config._settings import get_monitor_tool_wrap

    from .tool_handoff import maybe_reserve_monitor_tool_run
    from .tool_wrap import monitor_tool_run_words, resolve_monitor_tool_wrap

    request = context.request
    proc_argv, unwrapped_reason = resolve_monitor_tool_wrap(
        request.command,
        request.execution_argv,
        request.profile,
        request.cwd,
        get_monitor_tool_wrap(),
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
        monitor_id=context.monitor_id,
        starter_agent=context.lane_start.starter_agent,
    )
    reservation = handoff.reservation
    if not handoff.attempted or reservation is None or not reservation.reserved:
        reason = (reservation.error if reservation is not None else None) or (
            "the monitor command is not reservable"
            if not handoff.attempted
            else "a fresh tool run could not be reserved"
        )
        raise MonitorError(
            f"could not reacquire a tool run for staged monitor "
            f"{context.monitor_id!r} after held cleanup: {reason}"
        )
    return str(reservation.run_id)


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


__all__ = [
    "launch_from_persisted_payload",
]
