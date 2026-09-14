"""Manual monitor continuation resume and terminal-delivery recovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.continuation_capture import AuthoredCheckpoint

from .delivery import load_delivery_record
from .followup import FollowupLaunchResult, launch_followup_agent
from .models import MonitorRecord
from .naming import short_monitor_id
from .resume_adoption import (
    apply_resume_adoption as _apply_resume_adoption,
    collect_receiver_proofs as _collect_receiver_proofs,
)
from .resume_delivery_state import (
    DELIVERED_STATES as _DELIVERED_STATES,
    base_branch as _base_branch,
    delivery_identity as _delivery_identity,
    delivery_records as _delivery_records,
    existing_delivery_result as _existing_delivery_result,
    first_record as _first_record,
    mark_delivery_needs_attention as _mark_delivery_needs_attention,
    monitor_result as _monitor_result,
    record_resume_error as _record_resume_error,
    record_successful_resume as _record_successful_resume,
)
from .resume_support import (
    MonitorResumeError,
    MonitorResumeResult,
    capture_from_log as _capture_from_log,
    capture_needs_recovery as _capture_needs_recovery,
    conditional_completion_state as _conditional_completion_state,
    elapsed_seconds as _elapsed_seconds,
    load_checkpoint as _load_checkpoint,
    read_meta as _read_meta,
    selected_model as _selected_model,
)

_ACTIVE_DELIVERY_STATES = frozenset({"pending", "reserved", "dispatching"})


def resume_monitor(
    record: MonitorRecord,
    *,
    checkpoint_path: str | None = None,
    model: str | None = None,
) -> MonitorResumeResult:
    """Resume one terminal monitor's requested ordinary continuation."""

    meta = _read_meta(record.artifacts_dir)
    checkpoint = _load_checkpoint(checkpoint_path)
    selected_model = _selected_model(meta, model)
    result = _monitor_result(record, meta)
    monitor_id = str(result.get("monitor_id") or record.monitor_id or "monitor")
    result_id = str(result.get("result_id") or record.monitor_result_id or "result")
    _validate_resume_request(
        record,
        meta,
        checkpoint=checkpoint,
        model=model,
        suggested_command=_suggested_command(record),
    )

    base_branch = _base_branch(result, record)
    existing = _delivery_records(
        record,
        monitor_id=monitor_id,
        result_id=result_id,
    )
    proofs = _collect_receiver_proofs(record, existing)
    manual_revision = checkpoint is not None or model is not None
    decision, reused, checkpoint_ref = _apply_resume_adoption(
        record,
        meta,
        monitor_id=monitor_id,
        result_id=result_id,
        kind="manual_revision" if manual_revision else "ordinary",
        requested_branch=base_branch,
        checkpoint=checkpoint,
        selected_model=selected_model,
        next_action=str(meta.get("monitor_next_action") or ""),
        proofs=proofs,
    )
    branch = str(decision.get("selected_branch") or base_branch)
    outcome = str(decision.get("outcome") or "")
    if outcome == "already_delivered":
        delivered = load_delivery_record(
            record.artifacts_dir,
            {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
        ) or _first_record(existing, _DELIVERED_STATES)
        if delivered is None:
            delivered = {
                "key": {
                    "monitor_id": monitor_id,
                    "result_id": result_id,
                    "branch": branch,
                },
                "disposition": "acknowledged",
            }
        if checkpoint is not None or model is not None:
            raise MonitorResumeError(
                "monitor continuation has already been acknowledged; checkpoint "
                "or model changes cannot be applied after handoff",
                suggested_command=None,
                code="already_delivered",
            )
        return _existing_delivery_result(
            record,
            delivered,
            outcome="already_delivered",
            manual_revision=manual_revision,
            reused_revision=reused,
        )
    if outcome == "existing_receiver":
        active_record = load_delivery_record(
            record.artifacts_dir,
            {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
        )
        receiver = _delivery_identity(active_record)
        if receiver is not None:
            _record_successful_resume(record, meta, receiver)
        return MonitorResumeResult(
            monitor_id=monitor_id,
            branch=branch,
            agent_name=receiver,
            delivery_disposition=str((active_record or {}).get("disposition") or "")
            or None,
            launched=True,
            spawned=False,
            manual_revision=manual_revision,
            reused_revision=reused,
            ownership_outcome="existing_receiver",
            message=(
                f"Monitor {short_monitor_id(monitor_id)} already handed off to "
                f"{receiver}."
                if receiver
                else f"Monitor {short_monitor_id(monitor_id)} already has a receiver."
            ),
        )
    if outcome == "needs_attention" or not decision.get("admit"):
        reason = str(decision.get("reason") or "receiver ownership is ambiguous")
        raise MonitorResumeError(
            f"{reason}; retry with `{_suggested_command(record)}` after inspecting "
            "the existing delivery",
            suggested_command=_suggested_command(record),
            code="ambiguous_receiver",
        )

    launch = _launch_resume(
        record,
        meta,
        branch=branch,
        selected_model=selected_model if model is not None else None,
        checkpoint_ref=checkpoint_ref,
        retryable_pre_dispatch_failure=bool(
            decision.get("retryable_pre_dispatch_failure")
        ),
    )
    if not launch.launched:
        reason = launch.error or "follow-up launch failed"
        _mark_delivery_needs_attention(
            record.artifacts_dir,
            monitor_id=monitor_id,
            result_id=result_id,
            branch=branch,
            reason=reason,
        )
        raise MonitorResumeError(
            f"{reason}; retry with `{_suggested_command(record)}`",
            suggested_command=_suggested_command(record),
            code="launch_failed",
        )

    agent_name = launch.agent_name or _delivery_identity(
        load_delivery_record(
            record.artifacts_dir,
            {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
        )
    )
    _record_successful_resume(record, meta, agent_name)
    current = load_delivery_record(
        record.artifacts_dir,
        {"monitor_id": monitor_id, "result_id": result_id, "branch": branch},
    )
    delivery_disposition = str((current or {}).get("disposition") or "") or None
    return MonitorResumeResult(
        monitor_id=monitor_id,
        branch=branch,
        agent_name=agent_name,
        delivery_disposition=delivery_disposition,
        launched=True,
        spawned=True,
        manual_revision=manual_revision,
        reused_revision=reused,
        ownership_outcome="spawned_receiver",
        message=f"Resumed monitor {short_monitor_id(monitor_id)} with {agent_name}.",
    )


def reconcile_terminal_delivery(record: MonitorRecord) -> MonitorResumeResult | None:
    """Recover an already-created terminal delivery without creating a new one."""

    if record.monitor_state in {"running", "stopped", "lost"}:
        return None
    if not record.next_action:
        return None
    meta = _read_meta(record.artifacts_dir)
    result = _monitor_result(record, meta)
    monitor_id = str(result.get("monitor_id") or record.monitor_id or "monitor")
    result_id = str(result.get("result_id") or record.monitor_result_id or "result")
    existing = _delivery_records(record, monitor_id=monitor_id, result_id=result_id)
    if _first_record(existing, _ACTIVE_DELIVERY_STATES) is None:
        return None
    try:
        return resume_monitor(record)
    except MonitorResumeError as exc:
        _record_resume_error(record, meta, str(exc))
        return None


def _validate_resume_request(
    record: MonitorRecord,
    meta: Mapping[str, Any],
    *,
    checkpoint: AuthoredCheckpoint | None,
    model: str | None,
    suggested_command: str,
) -> None:
    if record.monitor_state == "running":
        raise MonitorResumeError(
            "monitor is still running; wait for it to finish before resuming",
            suggested_command=None,
            code="still_running",
        )
    if record.monitor_state in {"stopped", "lost"}:
        raise MonitorResumeError(
            f"monitor is {record.monitor_state}; that state is inspection-only",
            suggested_command=None,
            code=record.monitor_state,
        )
    if not str(meta.get("monitor_next_action") or "").strip():
        raise MonitorResumeError(
            "monitor was fire-and-forget and has no requested next action",
            suggested_command=None,
            code="fire_and_forget",
        )
    if _conditional_completion_state(meta, record):
        raise MonitorResumeError(
            "monitor resume cannot retry conditional host finalization",
            suggested_command=None,
            code="conditional_completion",
        )
    if _capture_needs_recovery(meta) and checkpoint is None and model is None:
        raise MonitorResumeError(
            f"monitor context capture needs manual recovery; retry with `{suggested_command} -k FILE`",
            suggested_command=f"{suggested_command} -k FILE",
            code="capture_recovery",
        )


def _launch_resume(
    record: MonitorRecord,
    meta: dict[str, Any],
    *,
    branch: str,
    selected_model: str | None,
    checkpoint_ref: str | None,
    retryable_pre_dispatch_failure: bool,
) -> FollowupLaunchResult:
    capture = _capture_from_log(record)
    return launch_followup_agent(
        record.artifacts_dir,
        meta,
        monitor_state=record.monitor_state,
        exit_code=record.exit_code,
        elapsed_seconds=record.elapsed_seconds or _elapsed_seconds(meta),
        capture=capture,
        timeout_kind=meta.get("monitor_timeout_kind")
        if isinstance(meta.get("monitor_timeout_kind"), str)
        else None,
        project_name=record.project_name,
        transfer_from_pid=record.pid,
        branch_override=branch,
        next_model_override=selected_model,
        checkpoint_ref_override=checkpoint_ref,
        retryable_pre_dispatch_failure=retryable_pre_dispatch_failure,
    )


def _suggested_command(record: MonitorRecord) -> str:
    return f"sase monitor resume {short_monitor_id(record.monitor_id)}"


__all__ = [
    "MonitorResumeError",
    "MonitorResumeResult",
    "reconcile_terminal_delivery",
    "resume_monitor",
]
