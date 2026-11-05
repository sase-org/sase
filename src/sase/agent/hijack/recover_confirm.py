"""Post-spawn confirmation: identity, claim, inheritance, settlement."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.core import (
    hijack_recovery_confirm,
    hijack_recovery_execution_wire_schema_version,
    hijack_recovery_rollback,
)
from sase.agent.hijack.recover_common import (
    RESULT_LAUNCHED,
    RESULT_UNCERTAIN,
    RESULT_ERROR,
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    RecoveryTarget,
    clean_string,
    fail_to_held,
    record_launch_stage,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
    resolver_identity,
)
from sase.agent.hijack.recover_settle import settle_recovery
from sase.agent.hijack.recovery_successor import BOOTSTRAP_ACK_SCHEMA_VERSION


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


def confirm_and_settle(
    resolving: Mapping[str, Any],
    *,
    subject: RecoverySubject,
    hijack_id: str,
    target: RecoveryTarget,
    reserved_name: str,
    launch_identity: str,
    binding: Mapping[str, str],
    launched: Any,
    context_mode: str,
    goal: str | None,
    bead: str | None,
    seams: RecoveryDeps,
) -> RecoveryResult:
    """Settle only from the successor's durable, identity-bound bootstrap ack."""
    successor_name = clean_string(getattr(launched, "agent_name", None))
    successor_pid = record_pid(getattr(launched, "pid", None))
    successor_artifacts = clean_string(getattr(launched, "artifacts_dir", None))
    base_detail: dict[str, Any] = {"context_mode": context_mode}
    ack = _wait_for_successor_ack(successor_artifacts, seams=seams)
    child_meta = _read_successor_meta(successor_artifacts)
    meta_pid = record_pid(child_meta.get("pid"))
    meta_token = clean_string(child_meta.get("process_identity"))
    token_reader = seams.process_identity_token or _process_identity_token
    try:
        observed_token = token_reader(successor_pid) if successor_pid else None
    except Exception:
        observed_token = None
    process_identity_matches = bool(
        successor_pid is not None
        and meta_pid == successor_pid
        and meta_token
        and observed_token == meta_token
    )
    admission = _observe_admission(binding["admission_request_id"], seams)
    admission_matches = _terminal_launched_request(
        admission,
        request_id=binding["admission_request_id"],
        admission_identity=binding["admission_identity"],
    )
    ack_schema_matches = _ack_schema_matches(ack)
    ack_lineage = _lineage_payload(ack.get("lineage")) if ack else {}
    from sase.agent.hijack.recover_subject import lineage_for

    expected_lineage = lineage_for(
        hijack_id=hijack_id,
        record=resolving,
        target=target,
    ).as_dict()
    expected_provider, expected_model, expected_effort = _target_parts(
        target.concrete_target
    )
    expected_workspace_num = record_workspace_num(resolving)
    expected_workspace_dir = clean_string(resolving.get("workspace_dir"))
    launched_workspace_num = record_workspace_num(
        {"workspace_num": getattr(launched, "workspace_num", None)}
    )
    launched_workspace_dir = clean_string(getattr(launched, "workspace_dir", None))
    launch_workspace_matches = bool(
        launched_workspace_num == expected_workspace_num
        and _same_path(launched_workspace_dir, expected_workspace_dir)
    )
    workspace_ack_matches = bool(
        ack is None
        or (
            clean_string(ack.get("project")) == clean_string(subject.project_name)
            and _positive_int(ack.get("workspace_num")) == expected_workspace_num
            and _same_path(ack.get("workspace_dir"), expected_workspace_dir)
        )
    )
    workspace_matches = launch_workspace_matches and workspace_ack_matches
    model_matches = bool(
        ack is None
        or (
            clean_string(ack.get("concrete_target")) == target.concrete_target
            and clean_string(ack.get("provider")) == expected_provider
            and clean_string(ack.get("model")) == expected_model
            and clean_string(ack.get("effort")) == expected_effort
        )
    )
    successor_identity_matches = bool(
        successor_name == reserved_name
        and clean_string(resolving.get("reserved_successor_name")) == reserved_name
        and clean_string(resolving.get("launch_identity")) == launch_identity
        and (
            ack is None
            or (
                clean_string(ack.get("launch_identity")) == launch_identity
                and clean_string(ack.get("successor_name")) == reserved_name
            )
        )
    )
    ack_bound = (
        bool(
            ack_schema_matches
            and successor_identity_matches
            and process_identity_matches
            and clean_string(ack.get("process_token")) == meta_token
        )
        if ack
        else False
    )
    predecessor_meta = subject.predecessor_meta
    expected_goal = _meta_value(predecessor_meta, "goal_id", "goal")
    expected_bead = _meta_value(predecessor_meta, "bead_id")
    if goal is not None:
        expected_goal = clean_string(goal)
    if bead is not None:
        expected_bead = clean_string(bead)
    repo_count = ack.get("transferred_repos") if ack else None
    inheritance_matches = bool(
        ack
        and ack.get("goal_verified") is True
        and ack.get("bead_verified") is True
        and ack.get("scope_verified") is True
        and ack.get("baselines_verified") is True
        and ack.get("inventory_verified") is True
        and ack.get("baseline_inherited") is True
        and isinstance(repo_count, int)
        and not isinstance(repo_count, bool)
        and repo_count >= 0
        and isinstance(ack.get("permission"), Mapping)
        and clean_string(ack.get("goal")) == expected_goal
        and clean_string(ack.get("bead")) == expected_bead
    )
    verify = seams.verify_claim or _default_verify_claim
    try:
        claim_matches = bool(
            verify(
                project_file=clean_string(resolving.get("project_file")),
                workspace_num=expected_workspace_num,
                pid=successor_pid,
            )
        )
    except Exception:
        claim_matches = False
    facts = {
        "schema_version": hijack_recovery_execution_wire_schema_version(),
        "launch_identity_matches": successor_identity_matches,
        "model_matches": model_matches,
        "workspace_matches": workspace_matches and claim_matches,
        "lineage_matches": ack is None or ack_lineage == expected_lineage,
        "ack_bound": ack_bound,
        "ack_matches": inheritance_matches,
        "request_in_flight": not admission_matches,
        "successor_observed": successor_pid is not None or successor_name is not None,
    }
    decision = hijack_recovery_confirm(dict(resolving), facts)
    if decision.get("outcome") != "settle":
        return _rollback_failed_confirmation(
            resolving,
            hijack_id=hijack_id,
            target=target,
            successor_name=successor_name or reserved_name,
            successor_pid=successor_pid,
            successor_artifacts=successor_artifacts,
            launched=launched,
            launch_identity=launch_identity,
            binding=binding,
            child_meta=child_meta,
            admission=admission,
            failure=str(decision.get("message") or "successor confirmation failed"),
            failure_code=str(decision.get("code") or "confirmation_failed"),
            detail={
                **base_detail,
                "confirmation": decision,
                "confirmation_facts": facts,
            },
            seams=seams,
        )

    successor_token = meta_token
    try:
        settled = settle_recovery(
            dict(resolving),
            action=target.action,
            successor_name=reserved_name,
            successor_pid=successor_pid,
            successor_process_identity_token=successor_token,
            successor_artifacts_dir=successor_artifacts,
            inheritance_acknowledged=True,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            admission_identity=binding["admission_identity"],
        )
    except RecoveryRefusal as exc:
        return _retain_confirmation(
            resolving,
            hijack_id=hijack_id,
            target=target,
            successor_name=reserved_name,
            launch_identity=launch_identity,
            binding=binding,
            message=exc.message,
            detail={**base_detail, "launch_stage": "prepared"},
        )
    except ledger.HijackLedgerConflict:
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) == "resolved" and (
            clean_string(current.get("reserved_successor_name")) == reserved_name
        ):
            return RecoveryResult(
                kind=RESULT_LAUNCHED,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=reserved_name,
                launch_identity=launch_identity,
                admission_request_id=binding["admission_request_id"],
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message="Recovery settled by a concurrent confirmation",
                detail={**base_detail, "launch_stage": "confirmed"},
            )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "Settlement lost a concurrent write; the record retains "
                "resolving for reconciliation"
            ),
            detail={**base_detail, "launch_stage": "prepared"},
        )
    return RecoveryResult(
        kind=RESULT_LAUNCHED,
        hijack_id=hijack_id,
        revision=record_revision(settled),
        action=target.action,
        successor=reserved_name,
        launch_identity=launch_identity,
        admission_request_id=binding["admission_request_id"],
        concrete_target=target.concrete_target,
        model_changed=target.model_changed,
        message=f"Recovery {target.action} launched {reserved_name} in the held workspace",
        detail={**base_detail, "launch_stage": "confirmed"},
    )


def _retain_confirmation(
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


def _rollback_failed_confirmation(
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
    return _retain_confirmation(
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


def _observe_admission(request_id: str, seams: RecoveryDeps) -> dict[str, Any]:
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
            observation = _observe_admission(request_id, seams)
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


def _terminal_launched_request(
    observation: Mapping[str, Any],
    *,
    request_id: str,
    admission_identity: str,
) -> bool:
    return bool(
        _admission_binding_matches(
            observation,
            request_id=request_id,
            admission_identity=admission_identity,
        )
        and observation.get("state") == "launched"
        and observation.get("in_flight") is False
    )


def _wait_for_successor_ack(
    artifacts_dir: str | None, *, seams: RecoveryDeps
) -> Mapping[str, Any] | None:
    if not artifacts_dir:
        return None
    reader = seams.read_ack
    if reader is None:
        from sase.agent.hijack.recovery_successor import read_recovery_ack

        reader = read_recovery_ack
    pause = seams.sleep or time.sleep
    try:
        interval = float(seams.settle_poll_seconds)
    except (TypeError, ValueError):
        interval = 0.5
    interval = interval if interval > 0 else 0.5
    deadline = time.monotonic() + max(0.0, float(seams.settle_timeout_seconds))
    while True:
        try:
            ack = reader(artifacts_dir)
        except Exception:
            ack = None
        if isinstance(ack, Mapping) and ack:
            return dict(ack)
        if time.monotonic() >= deadline:
            return None
        try:
            pause(interval)
        except Exception:
            return None


def _read_successor_meta(artifacts_dir: str | None) -> dict[str, Any]:
    if not artifacts_dir:
        return {}
    try:
        from sase.history.chat_fork.common import load_json_object

        value = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    except Exception:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _ack_schema_matches(ack: Mapping[str, Any] | None) -> bool:
    version = ack.get("schema_version") if ack else None
    return bool(
        isinstance(version, int)
        and not isinstance(version, bool)
        and version == BOOTSTRAP_ACK_SCHEMA_VERSION
    )


def _lineage_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except ValueError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _target_parts(value: str) -> tuple[str | None, str | None, str | None]:
    from sase.macro.effort import EFFORT_LEVELS

    stem = value
    effort: str | None = None
    base, separator, candidate = value.rpartition("@")
    if separator and candidate in EFFORT_LEVELS:
        stem, effort = base, candidate
    provider, separator, model = stem.partition("/")
    if not separator or not provider or not model:
        return None, None, None
    return provider, model, effort


def _meta_value(meta: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = clean_string(meta.get(key))
        if value:
            return value
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _same_path(left: Any, right: Any) -> bool:
    left_value = clean_string(left)
    right_value = clean_string(right)
    return bool(
        left_value
        and right_value
        and os.path.normcase(os.path.normpath(left_value))
        == os.path.normcase(os.path.normpath(right_value))
    )


def _process_identity_token(pid: int) -> str | None:
    from sase.core.process_identity import process_identity_token

    try:
        return process_identity_token(int(pid)) or None
    except Exception:
        return None


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
    current_token = _process_identity_token(pid)
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
    after = _process_identity_token(pid)
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
    if launched_num != workspace_num or not _same_path(launched_dir, workspace_dir):
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


def _default_verify_claim(
    *,
    project_file: str | None,
    workspace_num: int | None,
    pid: int | None,
) -> bool:
    return successor_holds_claim(
        project_file=project_file, workspace_num=workspace_num, pid=pid
    )
