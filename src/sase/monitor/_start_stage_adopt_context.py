"""Reconstruct staged monitor launch context and workspace claims."""

from __future__ import annotations

from dataclasses import replace
import json
import shlex
from pathlib import Path
from typing import Any

from ._start_stage_shared import optional_str
from .logs import monitor_log_path
from .models import MonitorError
from .request import StartMonitorRequest
from .start_claim import preflight_monitor_workspace_claim
from .start_lane import LaneStart
from .start_launch import MonitorLaunchContext
from .start_runtime import monitor_claim_error


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


def reconstruct_launch_context(
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
    resources = (
        payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    )
    frozen_tool_run_id = optional_str(claim.get("tool_run_id")) or optional_str(
        resources.get("tool_run_id") if isinstance(resources, dict) else None
    )
    member_tool_run_id = optional_str(meta.get("monitor_tool_run_id"))
    tool_run_id = member_tool_run_id or frozen_tool_run_id
    tool_run_joined_raw = meta.get("monitor_tool_run_joined")
    tool_run_joined = (
        tool_run_joined_raw
        if isinstance(tool_run_joined_raw, bool)
        else bool(claim.get("tool_run_joined"))
    )
    replaced_staged_join = bool(
        member_tool_run_id
        and frozen_tool_run_id
        and member_tool_run_id != frozen_tool_run_id
        and tool_run_joined_raw is False
    )
    join_mode = (
        "none" if replaced_staged_join else str(claim.get("join_mode") or "none")
    )
    label = str(meta.get("monitor_label") or payload.get("label") or "")
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
        label=label,
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
        join_run_id=(
            None if replaced_staged_join else optional_str(claim.get("join_run_id"))
        ),
    )
    overlay_raw = claim.get("proc_env_overlay") or []
    overlay: list[tuple[str, str]] = []
    if isinstance(overlay_raw, list):
        for item in overlay_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                overlay.append((str(item[0]), str(item[1])))
    proc_argv_raw = claim.get("proc_argv") or []
    proc_argv = tuple(str(part) for part in proc_argv_raw) if proc_argv_raw else None
    proc_tags = tuple(str(tag) for tag in (claim.get("proc_tags") or ()))
    if replaced_staged_join and tool_run_id:
        from sase.tool.handoff import owner_tags, worker_argv, worker_env_overlay

        proc_argv = tuple(worker_argv(tool_run_id))
        proc_tags = tuple(owner_tags(tool_run_id))
        overlay = sorted(worker_env_overlay().items())
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
        label=label,
        starter_artifacts_dir=optional_str(claim.get("starter_artifacts_dir")),
        request_fingerprint=str(payload.get("request_fingerprint") or ""),
        monitor_id=str(payload.get("monitor_id") or meta.get("monitor_id") or ""),
        suffix=str(claim.get("suffix") or ""),
        bound_completion_ref=None,
        artifacts_dir=artifacts_dir,
        log_path=log_path,
        reserved_tool_run_id=tool_run_id,
        tool_run_joined=tool_run_joined,
        proc_argv=proc_argv,
        proc_tags=proc_tags,
        proc_env_overlay=tuple(overlay),
        unwrapped_reason=optional_str(claim.get("unwrapped_reason")),
        join_mode=join_mode,
        member_state="staged",
        staged_id=optional_str(payload.get("staged_id")),
        starter_provider=optional_str(claim.get("starter_provider")),
    )


def revalidate_claim(context: MonitorLaunchContext) -> MonitorLaunchContext:
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
