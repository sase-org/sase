"""Adopt a staged monitor member from its frozen payload.

Adoption path of the internal staged-monitor transaction split from
:mod:`sase.monitor.start_stage`. Reconstructs the launch context under the
lane lock, revalidates the workspace claim and reserved run, binds any
reserved prepared completion, then submits the proc.
"""

from __future__ import annotations

from dataclasses import replace
import json
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
        raise MonitorError(str(exc)) from exc
    return replace(context, bound_completion_ref=request.completion_ref)


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
