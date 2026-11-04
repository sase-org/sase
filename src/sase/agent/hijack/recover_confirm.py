"""Post-spawn confirmation: identity, claim, inheritance, settlement."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
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
    code_detail,
    current_resolution_result,
    fail_to_held,
    record_launch_stage,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
    resolver_identity,
)
from sase.agent.hijack.recover_settle import settle_recovery
from sase.agent.hijack.recover_settle import gather_recovery_inheritance
from sase.agent.hijack.recovery_successor import (
    RecoveryInheritanceError,
    require_recovery_inheritance,
    rollback_recovery_preparation,
    write_recovery_ack,
)

LOG = logging.getLogger(__name__)


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
    successor_name = clean_string(getattr(launched, "agent_name", None))
    successor_pid = record_pid(getattr(launched, "pid", None))
    successor_artifacts = clean_string(getattr(launched, "artifacts_dir", None))
    base_detail: dict[str, Any] = {"context_mode": context_mode}
    if not successor_name or successor_name != reserved_name:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error=(
                f"successor identity {successor_name!r} does not match the "
                f"reserved {reserved_name!r}"
            ),
        )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=successor_name or reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "The successor identity does not match the reservation; "
                "the record retains resolving for reconciliation"
            ),
            detail={**base_detail, "launch_stage": "prepared"},
        )
    successor_token: str | None = None
    if successor_pid is not None:
        try:
            _, successor_token = resolver_identity(pid=successor_pid)
        except Exception:
            successor_token = None
    _wait_for_successor_meta(
        successor_artifacts,
        timeout=seams.settle_timeout_seconds,
        sleep=seams.sleep,
        poll=seams.settle_poll_seconds,
    )
    gather = seams.gather_inheritance or (
        lambda artifacts, **kwargs: gather_recovery_inheritance(
            subject, artifacts, **kwargs
        )
    )
    try:
        evidence = gather(
            successor_artifacts,
            goal=goal,
            bead=bead,
        )
    except Exception as exc:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error=f"inheritance observation failed: {exc}",
        )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "Inheritance evidence could not be observed; the record "
                f"retains resolving for reconciliation: {exc}"
            ),
            detail={**base_detail, "launch_stage": "prepared"},
        )
    if evidence is None:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error="successor boot evidence is not yet observable",
        )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "The successor has not booted far enough to confirm; the "
                "record retains resolving for reconciliation"
            ),
            detail={**base_detail, "launch_stage": "prepared"},
        )
    verify = seams.verify_claim or _default_verify_claim
    claim_ok = False
    try:
        claim_ok = bool(
            verify(
                project_file=clean_string(resolving.get("project_file")),
                workspace_num=record_workspace_num(resolving),
                pid=successor_pid,
            )
        )
    except Exception:
        claim_ok = False
    if not claim_ok:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error="successor workspace claim is not yet observable",
        )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "The successor workspace claim is not yet observable; the "
                "record retains resolving for reconciliation"
            ),
            detail={**base_detail, "launch_stage": "prepared"},
        )
    try:
        ack = require_recovery_inheritance(
            predecessor_goal=evidence.predecessor_goal,
            successor_goal=evidence.successor_goal,
            predecessor_bead=evidence.predecessor_bead,
            successor_bead=evidence.successor_bead,
            baseline_inherited=evidence.baseline_inherited,
            baseline_diagnostics=list(evidence.baseline_diagnostics),
            predecessor_repo_count=evidence.predecessor_repo_count,
            transferred_repo_count=evidence.transferred_repo_count,
            repo_diagnostics=list(evidence.repo_diagnostics),
            predecessor_autonomy=evidence.predecessor_autonomy,
            predecessor_name=evidence.predecessor_name,
            explicit_autonomy_selection=evidence.explicit_autonomy_selection,
            parent_meta=evidence.parent_meta,
            child_meta=evidence.child_meta,
        )
    except RecoveryInheritanceError as exc:
        rollback_recovery_preparation(artifacts_dir=successor_artifacts)
        _terminate_successor(successor_pid, terminate_fn=seams.terminate_pid)
        fail_to_held(dict(resolving), str(exc))
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("inheritance_failed"),
            hijack_id=hijack_id,
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                f"Required inheritance failed; the record returned to held "
                f"with an error: {exc}"
            ),
        )
    if successor_artifacts:
        try:
            write_recovery_ack(successor_artifacts, ack)
        except OSError as exc:
            rollback_recovery_preparation(artifacts_dir=successor_artifacts)
            _terminate_successor(successor_pid, terminate_fn=seams.terminate_pid)
            fail_to_held(dict(resolving), f"ack write failed: {exc}")
            return RecoveryResult(
                kind=RESULT_ERROR,
                detail=code_detail("ack_failed"),
                hijack_id=hijack_id,
                action=target.action,
                successor=successor_name,
                launch_identity=launch_identity,
                admission_request_id=binding["admission_request_id"],
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=f"Could not stage the inheritance acknowledgement: {exc}",
            )
    else:
        rollback_recovery_preparation(artifacts_dir=successor_artifacts)
        _terminate_successor(successor_pid, terminate_fn=seams.terminate_pid)
        fail_to_held(dict(resolving), "successor artifacts directory unknown")
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("missing_successor_artifacts"),
            hijack_id=hijack_id,
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message="The successor reported no artifacts directory",
        )
    try:
        settled = settle_recovery(
            dict(resolving),
            action=target.action,
            successor_name=successor_name,
            successor_pid=successor_pid,
            successor_process_identity_token=successor_token,
            successor_artifacts_dir=successor_artifacts,
            inheritance_acknowledged=True,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            admission_identity=binding["admission_identity"],
        )
    except RecoveryRefusal as exc:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error=exc.message,
        )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=successor_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=exc.message,
            detail={**base_detail, "launch_stage": "prepared"},
        )
    except ledger.HijackLedgerConflict:
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) == "resolved" and (
            clean_string(current.get("reserved_successor_name")) == successor_name
        ):
            return RecoveryResult(
                kind=RESULT_LAUNCHED,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=successor_name,
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
            successor=successor_name,
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
        successor=successor_name,
        launch_identity=launch_identity,
        admission_request_id=binding["admission_request_id"],
        concrete_target=target.concrete_target,
        model_changed=target.model_changed,
        message=(
            f"Recovery {target.action} launched {successor_name} in the held workspace"
        ),
        detail={**base_detail, "launch_stage": "confirmed"},
    )


def _default_verify_claim(
    *,
    project_file: str | None,
    workspace_num: int | None,
    pid: int | None,
) -> bool:
    return successor_holds_claim(
        project_file=project_file, workspace_num=workspace_num, pid=pid
    )


def _terminate_successor(
    pid: int | None,
    *,
    terminate_fn: Callable[[int], None] | None = None,
) -> None:
    """Best-effort stop of a successor that failed validation.

    A partially confirmed successor must not run while its record returns
    to held: termination is best-effort and never raises, and custody keeps
    the held workspace pinned either way.
    """
    if pid is None:
        return
    if terminate_fn is not None:
        try:
            terminate_fn(int(pid))
        except Exception:
            LOG.warning("recovery successor termination failed", exc_info=True)
        return
    import signal

    try:
        os.kill(int(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return


def _wait_for_successor_meta(
    successor_artifacts_dir: str | None,
    *,
    timeout: float,
    sleep: Callable[[float], None] | None,
    poll: float = 0.5,
) -> None:
    if not successor_artifacts_dir:
        return
    pause = sleep or time.sleep
    try:
        interval = float(poll)
    except (TypeError, ValueError):
        interval = 0.5
    if interval <= 0:
        interval = 0.5
    deadline = time.monotonic() + max(0.0, float(timeout))
    target = Path(successor_artifacts_dir) / "agent_meta.json"
    while time.monotonic() < deadline:
        try:
            if target.is_file() and target.stat().st_size > 0:
                return
        except OSError:
            pass
        try:
            pause(interval)
        except Exception:
            return
