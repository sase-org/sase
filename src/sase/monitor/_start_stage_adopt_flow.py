"""Launch and retry a staged monitor from its frozen payload."""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Any
from collections.abc import Callable

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    validate_staged_monitor_launch_payload,
)
from sase.logs._bounded import log_file_lock

from ._start_stage_shared import claim_context
from ._start_stage_adopt_context import reconstruct_launch_context, revalidate_claim
from ._start_stage_adopt_prepared import bind_staged_prepared_completion
from ._start_stage_adopt_proc import adopt_existing_proc
from .models import MonitorError, MonitorRecord
from .staged_owner import launch_payload_path
from .start_launch import MonitorLaunchContext
from .start_metadata import read_start_meta
from .start_stage_cleanup import cleanup_staged_monitor
from .start_timing import StartTimer
from .transaction import monitor_lane_lock_path


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


def launch_staged_payload(
    artifacts_dir: str,
    payload: dict[str, Any],
    *,
    starter_continuation_node_id: str | None = None,
    launch_callback: Callable[[MonitorLaunchContext, StartTimer], MonitorRecord],
) -> MonitorRecord:
    """Launch a staged monitor from its frozen payload under the lane lock."""
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
            write_json_marker_atomic(launch_payload_path(artifacts_dir), payload)
        return _launch_from_persisted_payload_locked(
            artifacts_dir, payload, claim, timer, launch_callback
        )


def _launch_from_persisted_payload_locked(
    artifacts_dir: str,
    payload: dict[str, Any],
    claim: dict[str, Any],
    timer: StartTimer,
    launch_callback: Callable[[MonitorLaunchContext, StartTimer], MonitorRecord],
) -> MonitorRecord:
    meta = read_start_meta(artifacts_dir)
    if str(meta.get("monitor_state") or "") == "running":
        from .store import read_monitor_marker

        project_name = str(claim.get("project_name") or "")
        existing = read_monitor_marker(project_name, artifacts_dir)
        if existing is not None:
            return existing
    try:
        recovered = adopt_existing_proc(artifacts_dir, payload, claim, meta, timer)
        if recovered is not None:
            return recovered
        context = reconstruct_launch_context(artifacts_dir, payload, claim, meta)
        context = revalidate_claim(context)
        context = _reacquire_settled_tool_run(context)
        _revalidate_reserved_run(context)
        context = bind_staged_prepared_completion(context, payload)
        return launch_callback(context, timer)
    except Exception:
        # Adoption failure holds the published handoff for recovery. Only an
        # explicit discard may remove that outer record.
        cleanup_staged_monitor(artifacts_dir, held=True)
        raise


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

    run_id = context.reserved_tool_run_id
    if not run_id or context.staged_id is None:
        return context
    shown = _show_reserved_run(context.monitor_id, run_id)
    run = shown.get("run") if isinstance(shown, dict) else None

    if context.join_mode == "staged" or context.tool_run_joined:
        return _reacquire_unusable_staged_join(context, run_id, run)

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
    fresh_run_id = _reserve_retry_tool_run(context)
    update_meta_field(context.artifacts_dir, "monitor_tool_run_id", fresh_run_id)
    from sase.tool.handoff import owner_tags, worker_argv, worker_env_overlay

    return replace(
        context,
        reserved_tool_run_id=fresh_run_id,
        proc_argv=tuple(worker_argv(fresh_run_id)),
        proc_tags=tuple(owner_tags(fresh_run_id)),
        proc_env_overlay=tuple(sorted(worker_env_overlay().items())),
    )


def _reacquire_unusable_staged_join(
    context: MonitorLaunchContext,
    run_id: str,
    run: object,
) -> MonitorLaunchContext:
    """Replace a missing or result-less staged join with an owned ToolRun."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    if _has_usable_join_result(run):
        return context
    if not _staged_record_still_live(context):
        return context
    if isinstance(run, dict):
        diagnostics = run.get("diagnostics")
        entries = (
            [str(entry) for entry in diagnostics]
            if isinstance(diagnostics, list)
            else []
        )
        if any(_DISCARD_MARKER in entry for entry in entries):
            return context
        reservation = run.get("staged_join_reservation")
        if (
            isinstance(reservation, dict)
            and str(reservation.get("staged_id") or "") == context.staged_id
            and str(reservation.get("monitor_id") or "") == context.monitor_id
        ):
            _release_staged_join_reservation(context, run_id)

    fresh_run_id = _reserve_retry_tool_run(context)
    update_meta_field(context.artifacts_dir, "monitor_tool_run_id", fresh_run_id)
    update_meta_field(context.artifacts_dir, "monitor_tool_run_joined", False)
    replacement_label = context.label.removesuffix(" (joined)")
    update_meta_field(context.artifacts_dir, "monitor_label", replacement_label)

    from sase.tool.handoff import owner_tags, worker_argv, worker_env_overlay

    return replace(
        context,
        request=replace(
            context.request,
            label=replacement_label,
            join_run_id=None,
        ),
        label=replacement_label,
        reserved_tool_run_id=fresh_run_id,
        tool_run_joined=False,
        join_mode="none",
        proc_argv=tuple(worker_argv(fresh_run_id)),
        proc_tags=tuple(owner_tags(fresh_run_id)),
        proc_env_overlay=tuple(sorted(worker_env_overlay().items())),
    )


def _has_usable_join_result(run: object) -> bool:
    """Return whether a joined run still has an outcome worth following."""

    if not isinstance(run, dict):
        return False
    if run.get("stop_request") is not None:
        return False
    state = str(run.get("state") or "")
    if state in {"created", "running"}:
        return True
    if not state:
        return False
    if str(run.get("terminal_cause") or "") == "stop_requested":
        return False
    return type(run.get("exit_code")) is int or type(run.get("signal")) is int


def _release_staged_join_reservation(
    context: MonitorLaunchContext, run_id: str
) -> None:
    """Release this stage's old join reservation before replacing its run."""

    from sase.core.tool_run import tool_run_release_staged_join

    result = tool_run_release_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": context.staged_id,
            "monitor_id": context.monitor_id,
        }
    )
    outcome = result.get("outcome") if isinstance(result, dict) else None
    if outcome not in {"released", "not_reserved"}:
        raise MonitorError(
            f"could not release staged join reservation for tool run {run_id} "
            f"before reacquiring it ({outcome or 'refused'})"
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
        # Staged join payloads freeze the display command into
        # ``execution_argv`` during serialization. For fallback, recover the
        # original ``sase tool run`` words from that command instead of
        # treating the serialized argv as a host-owned raw command.
        None
        if context.join_mode == "staged" or context.tool_run_joined
        else request.execution_argv,
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
