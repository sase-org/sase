"""Rollback confirmation failures and restore held workspace custody."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.core import (
    hijack_recovery_execution_wire_schema_version,
    hijack_recovery_rollback,
)
from sase.agent.hijack.recover_common import (
    RESULT_ERROR,
    RESULT_UNCERTAIN,
    RecoveryDeps,
    RecoveryResult,
    RecoveryTarget,
    clean_string,
    fail_to_held,
    record_launch_stage,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
)
from sase.agent.hijack._recover_confirm_utils import process_identity_token, same_path


def successor_holds_claim(
    *,
    project_file: str | None,
    workspace_num: int | None,
    pid: int | None,
) -> bool:
    """Return whether *pid* currently owns *workspace_num*.

    Identity alone never proves a successor; the claim check pairs the
    reserved name with live workspace custody before settlement.
    """
    if not project_file or workspace_num is None or pid is None:
        return False
    try:
        from sase.running_field import get_claimed_workspaces
    except Exception:
        return False
    try:
        claims = get_claimed_workspaces(project_file)
    except Exception:
        return False
    for claim in claims:
        try:
            claimed_num = int(claim.workspace_num)
            claimed_pid = int(claim.pid)
        except (TypeError, ValueError):
            continue
        if claimed_num == int(workspace_num) and claimed_pid == int(pid):
            return True
    return False


def retain_confirmation(
    resolving: Mapping[str, Any],
    *,
    hijack_id: str,
    target: RecoveryTarget,
    successor_name: str,
    launch_identity: str,
    binding: Mapping[str, str],
    message: str,
    detail: Mapping[str, Any],
) -> RecoveryResult:
    record_launch_stage(
        resolving,
        launch_identity,
        binding,
        stage="prepared",
        error=message,
    )
    current = reload_record(hijack_id, resolving)
    return RecoveryResult(
        kind=RESULT_UNCERTAIN,
        hijack_id=hijack_id,
        revision=record_revision(current),
        action=target.action,
        successor=successor_name,
        launch_identity=launch_identity,
        admission_request_id=binding["admission_request_id"],
        concrete_target=target.concrete_target,
        model_changed=target.model_changed,
        message=message,
        detail={**dict(detail), "launch_stage": "prepared"},
    )


def rollback_failed_confirmation(
    resolving: Mapping[str, Any],
    *,
    hijack_id: str,
    target: RecoveryTarget,
    successor_name: str,
    successor_pid: int | None,
    successor_artifacts: str | None,
    launched: Any,
    launch_identity: str,
    binding: Mapping[str, str],
    child_meta: Mapping[str, Any],
    admission: Mapping[str, Any],
    failure: str,
    failure_code: str,
    detail: Mapping[str, Any],
    seams: RecoveryDeps,
) -> RecoveryResult:
    request_state, request_observation = _make_request_non_dispatchable(
        admission,
        request_id=binding["admission_request_id"],
        admission_identity=binding["admission_identity"],
        seams=seams,
    )
    meta_pid = record_pid(child_meta.get("pid"))
    process_token = clean_string(child_meta.get("process_identity"))
    termination: Mapping[str, Any] = {"verified_dead": False, "state": "uncertain"}
    child_state = "uncertain"
    if (
        request_state is not None
        and successor_pid is not None
        and meta_pid == successor_pid
    ):
        terminate = seams.terminate_successor or _default_terminate_successor
        try:
            raw_termination = terminate(
                successor_pid,
                successor_artifacts,
                process_token,
            )
        except Exception as exc:  # noqa: BLE001 - failed stop retains custody
            raw_termination = {"verified_dead": False, "message": str(exc)}
        termination = _termination_observation(raw_termination)
        if termination.get("verified_dead") is True:
            child_state = "dead"
    custody_state = "uncertain"
    custody_observation: Mapping[str, Any] = {"restored": False}
    if child_state == "dead" and request_state is not None:
        restore = seams.restore_custody or _restore_held_workspace_custody
        try:
            restored, restore_message = restore(
                dict(resolving), successor_pid, launched
            )
        except Exception as exc:  # noqa: BLE001 - custody failures retain resolving
            restored, restore_message = False, str(exc)
        custody_observation = {
            "restored": bool(restored),
            "message": restore_message,
        }
        custody_state = "restored" if restored else "uncertain"
    rollback = hijack_recovery_rollback(
        dict(resolving),
        {
            "schema_version": hijack_recovery_execution_wire_schema_version(),
            "child_state": child_state,
            "custody": custody_state,
            "request_state": request_state or "uncertain",
        },
    )
    result_detail = {
        **dict(detail),
        "rollback": rollback,
        "admission_after_cancel": request_observation,
        "termination": dict(termination),
        "custody": dict(custody_observation),
    }
    if rollback.get("outcome") == "return_to_held":
        current = reload_record(hijack_id, resolving)
        fail_to_held(current, failure)
        current = reload_record(hijack_id, current)
        if clean_string(current.get("state")) == "held":
            return RecoveryResult(
                kind=RESULT_ERROR,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=successor_name,
                launch_identity=launch_identity,
                admission_request_id=binding["admission_request_id"],
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=f"Recovery confirmation failed; safe rollback returned the record to held: {failure}",
                detail={
                    **result_detail,
                    "code": failure_code,
                    "launch_stage": "failed",
                },
            )
        result_detail["rollback_write"] = "could not persist resolution_failed"
    return retain_confirmation(
        resolving,
        hijack_id=hijack_id,
        target=target,
        successor_name=successor_name,
        launch_identity=launch_identity,
        binding=binding,
        message=(
            f"{failure}; safe rollback is unproven and the record retains resolving"
        ),
        detail=result_detail,
    )


def observe_admission(request_id: str, seams: RecoveryDeps) -> dict[str, Any]:
    observe = seams.observe_admission
    if observe is None:
        from sase.agent.hijack.recovery_admission import observe_recovery_admission

        observe = observe_recovery_admission
    try:
        return dict(observe(request_id))
    except Exception as exc:  # noqa: BLE001 - missing status is uncertain
        return {"request_id": request_id, "state": "uncertain", "message": str(exc)}


def _make_request_non_dispatchable(
    admission: Mapping[str, Any],
    *,
    request_id: str,
    admission_identity: str,
    seams: RecoveryDeps,
) -> tuple[str | None, dict[str, Any]]:
    observation = dict(admission)
    if not _admission_binding_matches(
        observation,
        request_id=request_id,
        admission_identity=admission_identity,
    ):
        return None, observation
    if observation.get("in_flight"):
        cancel = seams.cancel_admission
        if cancel is None:
            from sase.agent.hijack.recovery_admission import (
                cancel_recovery_admission_for_rollback,
            )

            def cancel(rid: str, reason: str) -> dict[str, Any]:
                return cancel_recovery_admission_for_rollback(rid, reason=reason)

        try:
            observation = dict(
                cancel(request_id, "recovery successor confirmation failed")
            )
        except Exception as exc:  # noqa: BLE001 - cancellation must be proven
            observation = observe_admission(request_id, seams)
            observation["cancel_error"] = str(exc)
        if not _admission_binding_matches(
            observation,
            request_id=request_id,
            admission_identity=admission_identity,
        ):
            return None, observation
    state = str(observation.get("state") or "")
    if observation.get("in_flight"):
        return None, observation
    if state == "cancelled" and observation.get("cancel_requested") is True:
        return "canceled", observation
    if state == "launched":
        # The terminal launched receipt proves this exact request can no longer
        # dispatch another child. In the core rollback contract, `none` means
        # there is no remaining dispatchable request (the receipt stays durable).
        return "none", observation
    return None, observation


def _admission_binding_matches(
    observation: Mapping[str, Any],
    *,
    request_id: str,
    admission_identity: str,
) -> bool:
    return bool(
        clean_string(observation.get("request_id")) == request_id
        and clean_string(observation.get("dispatch_fingerprint")) == admission_identity
    )


def _termination_observation(value: Mapping[str, Any] | bool) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"verified_dead": value is True}


def _default_terminate_successor(
    pid: int,
    artifacts_dir: str | None,
    expected_token: str | None,
) -> dict[str, Any]:
    """Stop the recorded process tree and return only verified death evidence."""
    if not expected_token:
        return {"verified_dead": False, "state": "identity_missing"}
    current_token = process_identity_token(pid)
    if current_token and current_token != expected_token:
        return {"verified_dead": False, "state": "pid_recycled"}
    from sase.agent._user_kill_tree import terminate_agent_processes

    result = terminate_agent_processes(
        int(pid),
        artifacts_dir=artifacts_dir,
        protected_pids=(os.getpid(),),
    )
    status = str(getattr(result, "status", ""))
    success = bool(getattr(result, "success", False))
    survivors = tuple(getattr(result, "survivors", ()) or ())
    after = process_identity_token(pid)
    verified = bool(
        success
        and status in {"killed", "force_killed", "already_stopped"}
        and not survivors
        and after != expected_token
    )
    return {
        "verified_dead": verified,
        "state": status or "uncertain",
        "survivors": list(survivors),
        "message": getattr(result, "error", None),
    }


def _restore_held_workspace_custody(
    record: Mapping[str, Any], successor_pid: int | None, launched: Any
) -> tuple[bool, str]:
    """Restore the same pinned workspace to its recorded held owner."""
    project_file = clean_string(record.get("project_file"))
    workspace_num = record_workspace_num(record)
    workspace_dir = clean_string(record.get("workspace_dir"))
    expected_owner = record_pid(
        record.get("expected_claim_owner_pid")
        if record.get("expected_claim_owner_pid") is not None
        else record.get("pid")
    )
    if not project_file or workspace_num is None or not workspace_dir:
        return False, "the held project/workspace identity is incomplete"
    if expected_owner is None:
        return False, "the held workspace owner was not recorded"
    launched_num = record_workspace_num(
        {"workspace_num": getattr(launched, "workspace_num", None)}
    )
    launched_dir = clean_string(getattr(launched, "workspace_dir", None))
    if launched_num != workspace_num or not same_path(launched_dir, workspace_dir):
        return False, "the successor did not report the held workspace pair"

    from sase.running_field import (
        claim_workspace,
        get_claimed_workspaces,
        hold_workspace_claim,
        transfer_workspace_claim,
    )

    try:
        claims = [
            claim
            for claim in get_claimed_workspaces(project_file)
            if int(claim.workspace_num) == workspace_num
        ]
    except Exception as exc:
        return False, f"could not inspect workspace claims: {exc}"
    if len(claims) > 1:
        return False, f"workspace #{workspace_num} has multiple claims"
    if not claims:
        workflow = clean_string(getattr(launched, "workflow_name", None)) or "run"
        cl_name = clean_string(getattr(launched, "cl_name", None)) or str(
            record.get("agent_name") or ""
        )
        timestamp = clean_string(getattr(launched, "timestamp", None)) or ""
        claimed = claim_workspace(
            project_file,
            workspace_num,
            workflow,
            expected_owner,
            cl_name=cl_name,
            artifacts_timestamp=timestamp,
            pinned=True,
            caller_tag="hijack-recovery-rollback",
        )
        if not claimed.success:
            return False, claimed.error or "could not recreate the held workspace claim"
    else:
        claim = claims[0]
        owner = int(claim.pid)
        if owner not in {expected_owner, successor_pid}:
            return False, f"workspace #{workspace_num} is owned by foreign pid {owner}"
        if not claim.pinned:
            held = hold_workspace_claim(
                project_file,
                workspace_num,
                claim.workflow,
                claim.cl_name or "",
                claim.artifacts_timestamp or "",
                caller_tag="hijack-recovery-rollback",
                expected_pid=owner,
            )
            if not held.success:
                return False, held.error or "could not pin the held workspace claim"
        if owner != expected_owner:
            moved = transfer_workspace_claim(
                project_file,
                workspace_num,
                from_pid=owner,
                to_pid=expected_owner,
                new_workflow=claim.workflow,
                new_artifacts_timestamp=claim.artifacts_timestamp,
                cl_name=claim.cl_name,
                caller_tag="hijack-recovery-rollback",
            )
            if not moved.success:
                return False, moved.error or "could not restore held claim ownership"

    try:
        restored = [
            claim
            for claim in get_claimed_workspaces(project_file)
            if int(claim.workspace_num) == workspace_num
        ]
    except Exception as exc:
        return False, f"could not verify restored workspace claim: {exc}"
    if (
        len(restored) != 1
        or int(restored[0].pid) != expected_owner
        or not bool(restored[0].pinned)
    ):
        return False, "the exact held workspace claim was not restored and pinned"
    return True, "the fixed workspace claim is pinned under its recorded held owner"
