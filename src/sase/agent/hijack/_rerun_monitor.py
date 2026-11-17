"""Durable monitor command rerun through the held workspace.

Re-run starts a new monitor attempt for the exact recorded command in the
held workspace. It reuses the ledger CAS reservation (begin/record_launch/
complete_resolution) for duplicate and crash reconciliation, but it does not
use the LLM admission dispatcher: the successor is a monitor, launched
through the existing monitor-start machinery with the exact held claim
transferred, and confirmed through monitor ownership rather than the LLM
bootstrap ack.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import (
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    RecoveryTarget,
    clean_string,
    code_detail,
    fail_to_held,
    new_launch_identity,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
    reload_resolution,
    resolver_identity,
)
from sase.agent.hijack.recover_subject import lineage_for, session_base_for
from sase.agent.hijack.recover_target import resolve_effective_target


def recover_monitor_rerun(
    subject: RecoverySubject,
    record: dict[str, Any],
    hijack_id: str,
    revision: int,
    *,
    expected_revision: int | None,
    goal: str | None,
    bead: str | None,
    seams: RecoveryDeps,
) -> RecoveryResult:
    """Execute one durable monitor rerun for a held hijack record."""
    _ = goal
    _ = bead
    if clean_string(record.get("scope")) != "monitor":
        raise RecoveryRefusal(
            "unsupported_action",
            "Rerun is available only for monitor records",
        )
    state = clean_string(record.get("state")) or ""
    if state == "resolved":
        try:
            from sase.agent.hijack.recover_reconcile import repair_settled_projection

            repair_settled_projection(record)
        except Exception:
            pass
        from sase.agent.hijack.recover_common import current_resolution_result

        return current_resolution_result(record, "already_resolved")
    if state == "resolving":
        if expected_revision is not None and expected_revision != revision:
            from sase.agent.hijack.recover_common import current_resolution_result

            result = current_resolution_result(record, "already_resolving")
            return RecoveryResult(
                kind=result.kind,
                hijack_id=result.hijack_id,
                revision=result.revision,
                action=result.action,
                successor=result.successor,
                launch_identity=result.launch_identity,
                admission_request_id=result.admission_request_id,
                concrete_target=result.concrete_target,
                model_changed=result.model_changed,
                message=(
                    f"Preview revision {expected_revision} is stale; the "
                    f"record is at revision {revision}"
                ),
                detail={**dict(result.detail), "code": "stale_revision"},
            )
        return _resume_rerun_resolution(record, hijack_id)
    if state != "held":
        from sase.agent.hijack.recover_common import TERMINAL_RECOVERY_STATES

        if state in TERMINAL_RECOVERY_STATES:
            raise RecoveryRefusal(
                "not_held",
                f"Keep-work recovery is unavailable while state is {state!r}",
            )
        raise RecoveryRefusal(
            "not_held",
            f"Keep-work recovery is unavailable while state is {state!r}",
        )
    preview_fn = seams.preview or _default_preview
    try:
        preview = preview_fn(record)
    except Exception as exc:
        raise RecoveryRefusal(
            getattr(exc, "code", "preview_error"),
            str(exc),
        ) from exc
    if expected_revision is not None and int(preview.revision) != expected_revision:
        raise RecoveryRefusal(
            "stale_revision",
            f"Preview revision {expected_revision} is stale; the record is "
            f"at revision {int(preview.revision)}",
        )
    row = preview.action("rerun")
    if row is None:
        raise RecoveryRefusal(
            "unsupported_action",
            "Recovery action 'rerun' is not available in this version, got 'rerun'",
        )
    target = resolve_effective_target(
        action="rerun",
        record=record,
        preview_action={
            "available": row.available,
            "reason": row.reason,
            "target": row.target,
        },
        model_override=None,
        prompt_text=None,
    )
    return _dispatch_rerun(
        subject,
        record,
        hijack_id,
        revision,
        target=target,
        seams=seams,
    )


def _default_preview(record: Mapping[str, Any]) -> Any:
    from sase.agent.hijack import preview as preview_module

    return preview_module.hijack_recovery_preview(dict(record))


def _resume_rerun_resolution(
    record: Mapping[str, Any],
    hijack_id: str,
) -> RecoveryResult:
    """Resume a resolving rerun without launching a duplicate command.

    This fast path never relaunches. Whether or not a successor monitor is
    already observable, custody stays ``resolving``: the next explicit
    reconcile adopts an existing successor through the normal confirmation
    path, or returns the record to held so a later explicit retry owns the
    relaunch.
    """
    from sase.agent.hijack.recover_common import current_resolution_result

    current = reload_record(hijack_id, dict(record))
    return current_resolution_result(dict(current), "already_resolving")


def _dispatch_rerun(
    subject: RecoverySubject,
    record: dict[str, Any],
    hijack_id: str,
    revision: int,
    *,
    target: RecoveryTarget,
    seams: RecoveryDeps,
) -> RecoveryResult:
    from sase.agent.hijack._rerun_request import (
        build_rerun_request,
        load_rerun_descriptor,
    )

    try:
        descriptor = load_rerun_descriptor(record)
    except RecoveryRefusal as exc:
        raise exc
    except Exception as exc:
        raise RecoveryRefusal(
            "rerun_unavailable",
            f"Could not load the monitor recovery descriptor: {exc}",
        ) from exc
    session_base = session_base_for(record, subject.predecessor_meta)
    if not session_base:
        raise RecoveryRefusal(
            "no_session",
            "The predecessor has no agent-session parent to attach the "
            "reserved successor to",
        )
    project_name = subject.project_name
    if not project_name:
        raise RecoveryRefusal(
            "unresolvable_successor",
            "Recovery requires the predecessor project name for strict dispatch",
        )
    resolve_plan = seams.resolve_session_plan or _default_resolve_session_plan
    try:
        plan = resolve_plan(session_base, project_name)
    except Exception as exc:
        raise RecoveryRefusal(
            "unresolvable_successor",
            f"Could not reserve the recovery successor identity: {exc}",
        ) from exc
    reserved_name = clean_string(getattr(plan, "agent_name", None))
    if not reserved_name:
        raise RecoveryRefusal(
            "unresolvable_successor",
            "The attach resolver produced no reserved successor name",
        )
    workspace_num = record_workspace_num(record)
    workspace_dir = clean_string(record.get("workspace_dir"))
    if workspace_num is None or not workspace_dir:
        raise RecoveryRefusal(
            "workspace_unavailable",
            "Recovery requires the predecessor's fixed positive workspace number "
            "and directory",
        )
    resolver_pid, resolver_token = resolver_identity()
    launch_identity = new_launch_identity()
    request_id = f"hijack-rerun-{hijack_id}-{launch_identity[:12]}"
    begin_event: dict[str, Any] = {
        "event": "begin_resolution",
        "action": "rerun",
        "reserved_successor_name": reserved_name,
        "concrete_target_model": target.concrete_target,
        "model_changed": target.model_changed,
        "resolver_pid": resolver_pid,
        "launch_identity": launch_identity,
        "admission_request_id": request_id,
        "admission_identity": launch_identity,
    }
    if resolver_token:
        begin_event["resolver_process_identity_token"] = resolver_token
    try:
        resolving = dict(ledger.cas_advance_record(record, begin_event))
    except ledger.HijackLedgerConflict:
        return reload_resolution(hijack_id, revision)
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected",
            f"The recovery reservation was rejected: {exc}",
        ) from exc
    try:
        resolving = dict(
            ledger.cas_advance_record(
                resolving,
                {
                    "event": "record_launch",
                    "launch_identity": launch_identity,
                    "admission_request_id": request_id,
                    "admission_identity": launch_identity,
                    "launch_stage": "prepared",
                },
            )
        )
    except ledger.HijackLedgerConflict:
        current = reload_record(hijack_id, resolving)
        return _already_resolving(current, hijack_id)
    except ValueError as exc:
        fail_to_held(resolving, f"The admission binding was rejected: {exc}")
        raise RecoveryRefusal(
            "ledger_rejected",
            f"The admission binding was rejected: {exc}",
        ) from exc
    try:
        request = build_rerun_request(
            record,
            descriptor,
            project_name=project_name,
            session_base=session_base,
            custody_pid=record.get("expected_claim_owner_pid"),
        )
    except RecoveryRefusal as exc:
        fail_to_held(resolving, exc.message)
        raise
    except Exception as exc:
        fail_to_held(resolving, f"Could not build the rerun request: {exc}")
        return RecoveryResult(
            kind="error",
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action="rerun",
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Could not build the rerun request: {exc}",
            detail={**dict(code_detail("rerun_unavailable")), "launch_stage": "failed"},
        )
    start_fn = seams.spawn_successor or _default_start_monitor
    try:
        launched = start_fn(request)
    except Exception as exc:
        fail_to_held(resolving, f"Rerun monitor start failed: {exc}")
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) != "held":
            return RecoveryResult(
                kind="uncertain",
                hijack_id=hijack_id,
                revision=record_revision(current),
                action="rerun",
                successor=reserved_name,
                launch_identity=launch_identity,
                admission_request_id=request_id,
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=(
                    "Rerun monitor start failed, but the reservation could not "
                    f"be returned to held: {exc}"
                ),
                detail={"code": "launch_failed", "launch_stage": "failed"},
            )
        return RecoveryResult(
            kind="error",
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="rerun",
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Rerun monitor start failed: {exc}",
            detail={"code": "launch_failed", "launch_stage": "failed"},
        )
    return _confirm_rerun(
        resolving,
        subject=subject,
        hijack_id=hijack_id,
        target=target,
        reserved_name=reserved_name,
        launch_identity=launch_identity,
        request_id=request_id,
        launched=launched,
        descriptor=descriptor,
        seams=seams,
    )


def _already_resolving(current: Mapping[str, Any], hijack_id: str) -> RecoveryResult:
    from sase.agent.hijack.recover_common import current_resolution_result

    state = clean_string(current.get("state")) or ""
    if state == "resolved":
        return current_resolution_result(dict(current), "already_resolved")
    return current_resolution_result(dict(current), "already_resolving")


def _confirm_rerun(
    resolving: Mapping[str, Any],
    *,
    subject: RecoverySubject,
    hijack_id: str,
    target: RecoveryTarget,
    reserved_name: str,
    launch_identity: str,
    request_id: str,
    launched: Any,
    descriptor: Mapping[str, Any],
    seams: RecoveryDeps,
) -> RecoveryResult:

    successor_name = clean_string(getattr(launched, "member_agent_name", None))
    successor_artifacts = clean_string(getattr(launched, "artifacts_dir", None))
    successor_pid = record_pid(getattr(launched, "pid", None))
    launched_monitor_id = clean_string(getattr(launched, "monitor_id", None))
    launched_command = clean_string(getattr(launched, "command", None))
    launched_cwd = clean_string(getattr(launched, "cwd", None))
    launched_workspace_num: int | None = None
    try:
        raw_num = getattr(launched, "workspace_num", None)
        if isinstance(raw_num, int) and not isinstance(raw_num, bool):
            launched_workspace_num = raw_num
    except Exception:
        launched_workspace_num = None
    launched_workspace_dir = clean_string(getattr(launched, "workspace_dir", None))
    if launched_workspace_dir is None:
        launched_workspace_dir = clean_string(getattr(launched, "artifacts_dir", None))
        # MonitorRecord carries workspace via lane claim; fall back to held pair
        # only for the path comparison below when the seam omits it.
    expected_num = record_workspace_num(resolving)
    expected_dir = clean_string(resolving.get("workspace_dir"))
    expected_command = clean_string(descriptor.get("command"))
    expected_cwd = clean_string(descriptor.get("cwd")) or expected_dir
    old_monitor_id = clean_string(descriptor.get("monitor_id"))
    errors: list[str] = []
    if not successor_name:
        errors.append("the rerun monitor has no member name")
    if not successor_artifacts:
        errors.append("the rerun monitor has no artifacts directory")
    if launched_monitor_id and old_monitor_id and launched_monitor_id == old_monitor_id:
        errors.append("the rerun monitor reused the interrupted monitor id")
    if expected_command and launched_command != expected_command:
        errors.append(
            f"the rerun monitor command {launched_command!r} does not match "
            f"the recorded command {expected_command!r}"
        )
    if (
        expected_cwd
        and launched_cwd
        and os.path.normpath(launched_cwd) != os.path.normpath(expected_cwd)
    ):
        errors.append(
            f"the rerun monitor cwd {launched_cwd!r} does not match "
            f"the recorded cwd {expected_cwd!r}"
        )
    if expected_num is not None and launched_workspace_num is not None:
        if launched_workspace_num != expected_num:
            errors.append(
                f"the rerun monitor workspace #{launched_workspace_num} does not match "
                f"the held workspace #{expected_num}"
            )
    if expected_dir and launched_workspace_dir:
        try:
            if os.path.normpath(launched_workspace_dir) != os.path.normpath(
                expected_dir
            ):
                # Only enforce when the seam reports a real workspace dir, not
                # the artifacts dir fallback above.
                artifacts_fallback = successor_artifacts and os.path.normpath(
                    launched_workspace_dir
                ) == os.path.normpath(successor_artifacts)
                if not artifacts_fallback:
                    errors.append(
                        f"the rerun monitor workspace {launched_workspace_dir!r} does "
                        f"not match the held workspace {expected_dir!r}"
                    )
        except Exception:
            pass
    verify = seams.verify_claim or _default_verify_claim
    try:
        claim_ok = bool(
            verify(
                project_file=clean_string(resolving.get("project_file")),
                workspace_num=expected_num,
                pid=successor_pid,
            )
        )
    except Exception:
        claim_ok = False
    if not claim_ok:
        errors.append("the rerun monitor does not own the held workspace claim")
    if errors:
        fail_to_held(resolving, "; ".join(errors))
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) != "held":
            return RecoveryResult(
                kind="uncertain",
                hijack_id=hijack_id,
                revision=record_revision(current),
                action="rerun",
                successor=successor_name or reserved_name,
                launch_identity=launch_identity,
                admission_request_id=request_id,
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=(
                    "Rerun monitor confirmation failed, but the reservation "
                    f"could not be returned to held: {'; '.join(errors)}"
                ),
                detail={"code": "confirmation_failed", "launch_stage": "failed"},
            )
        return RecoveryResult(
            kind="error",
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="rerun",
            successor=successor_name or reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Rerun monitor confirmation failed: {'; '.join(errors)}",
            detail={"code": "confirmation_failed", "launch_stage": "failed"},
        )
    try:
        from sase.agent.hijack._preview_monitor import (
            preserve_monitor_followup_suppression,
        )

        predecessor_dir = clean_string(resolving.get("artifacts_dir"))
        if predecessor_dir:
            preserve_monitor_followup_suppression(predecessor_dir)
    except Exception:
        pass
    try:
        settled = dict(
            ledger.cas_advance_record(
                dict(resolving),
                {
                    "event": "complete_resolution",
                    "successor_name": successor_name or reserved_name,
                    "successor_pid": successor_pid,
                    "successor_artifacts_dir": successor_artifacts,
                    "launch_identity": launch_identity,
                    "admission_request_id": request_id,
                    "admission_identity": launch_identity,
                    "launch_stage": "confirmed",
                },
            )
        )
    except ledger.HijackLedgerConflict:
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) == "resolved":
            from sase.agent.hijack.recover_common import current_resolution_result

            return current_resolution_result(dict(current), "already_resolved")
        return RecoveryResult(
            kind="uncertain",
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="rerun",
            successor=successor_name or reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message="Rerun monitor launched but settlement lost its write",
            detail={"code": "settlement_conflict", "launch_stage": "dispatching"},
        )
    except ValueError as exc:
        fail_to_held(resolving, f"Rerun settlement was rejected: {exc}")
        current = reload_record(hijack_id, resolving)
        return RecoveryResult(
            kind="error",
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="rerun",
            successor=successor_name or reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Rerun settlement was rejected: {exc}",
            detail={"code": "settlement_rejected", "launch_stage": "failed"},
        )
    try:
        _settle_predecessor_rerun(
            settled,
            successor_name=successor_name or reserved_name,
            successor_artifacts=successor_artifacts,
            successor_pid=successor_pid,
        )
    except Exception as exc:
        return RecoveryResult(
            kind="uncertain",
            hijack_id=hijack_id,
            revision=record_revision(settled),
            action="rerun",
            successor=successor_name or reserved_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Rerun monitor launched but predecessor settlement failed: {exc}",
            detail={"code": "settlement_failed", "launch_stage": "confirmed"},
        )
    return RecoveryResult(
        kind="launched",
        hijack_id=hijack_id,
        revision=record_revision(settled),
        action="rerun",
        successor=successor_name or reserved_name,
        launch_identity=launch_identity,
        admission_request_id=request_id,
        concrete_target=target.concrete_target,
        model_changed=target.model_changed,
        message=(
            f"Rerun launched {successor_name or reserved_name} in the held workspace."
        ),
        detail={"launch_stage": "confirmed"},
    )


def _settle_predecessor_rerun(
    resolved: Mapping[str, Any],
    *,
    successor_name: str | None,
    successor_artifacts: str | None,
    successor_pid: int | None,
) -> None:
    """Mark the predecessor hijacked without reviving automatic delivery."""
    import json

    from sase.agent.hijack._preview_monitor import preserve_monitor_followup_suppression

    artifacts_dir = clean_string(resolved.get("artifacts_dir"))
    if not artifacts_dir:
        return
    preserve_monitor_followup_suppression(artifacts_dir)
    done_path = Path(artifacts_dir) / "done.json"
    try:
        payload = json.loads(done_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    recovery = payload.get("recovery")
    if not isinstance(recovery, dict):
        recovery = {}
    else:
        recovery = dict(recovery)
    recovery.update(
        {
            "successor": successor_name,
            "successor_artifacts_dir": successor_artifacts,
            "successor_pid": successor_pid,
            "action": "rerun",
        }
    )
    payload["recovery"] = recovery
    if payload.get("monitor_followup_outcome") != "hijacked":
        payload["monitor_followup_outcome"] = "hijacked"
    try:
        from sase.notification_gates.durability import atomic_write_json

        atomic_write_json(done_path, payload)
    except OSError:
        return


def _default_resolve_session_plan(session_base: str, project_name: str | None) -> Any:
    from sase.agent import _agent_session_attach_resolution as resolution
    from sase.agent.detached_child import AgentSessionAttachDirective

    if not project_name:
        raise ValueError("recovery requires the predecessor project name")
    return resolution.resolve_agent_session_attach_plan(
        AgentSessionAttachDirective(parent=session_base, suffix="@"),
        project_name=project_name,
    )


def _default_start_monitor(request: Any) -> Any:
    from sase.monitor.start_flow import start_monitor

    return start_monitor(request)


def _default_verify_claim(
    *,
    project_file: str | None,
    workspace_num: int | None,
    pid: int | None,
) -> bool:
    if not project_file or workspace_num is None or pid is None:
        return False
    try:
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if int(claim.workspace_num) == int(workspace_num) and int(claim.pid) == int(
                pid
            ):
                return True
    except Exception:
        return False
    return False


__all__ = ["recover_monitor_rerun"]
