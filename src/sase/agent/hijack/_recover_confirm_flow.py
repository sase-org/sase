"""Successor confirmation and settlement orchestration."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.core import (
    hijack_recovery_confirm,
    hijack_recovery_execution_wire_schema_version,
)
from sase.agent.hijack.recover_common import (
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_UNCERTAIN,
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    RecoveryTarget,
    clean_string,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
)
from sase.agent.hijack.recover_settle import settle_recovery
from sase.agent.hijack._recover_confirm_rollback import (
    observe_admission,
    retain_confirmation,
    rollback_failed_confirmation,
    successor_holds_claim,
)
from sase.agent.hijack._recover_confirm_utils import process_identity_token, same_path
from sase.agent.hijack.recovery_successor import BOOTSTRAP_ACK_SCHEMA_VERSION


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
    token_reader = seams.process_identity_token or process_identity_token
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
    admission = observe_admission(binding["admission_request_id"], seams)
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
        and same_path(launched_workspace_dir, expected_workspace_dir)
    )
    workspace_ack_matches = bool(
        ack is None
        or (
            clean_string(ack.get("project")) == clean_string(subject.project_name)
            and _positive_int(ack.get("workspace_num")) == expected_workspace_num
            and same_path(ack.get("workspace_dir"), expected_workspace_dir)
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
        return rollback_failed_confirmation(
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
        return retain_confirmation(
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


def _terminal_launched_request(
    observation: Mapping[str, Any],
    *,
    request_id: str,
    admission_identity: str,
) -> bool:
    return bool(
        clean_string(observation.get("request_id")) == request_id
        and clean_string(observation.get("dispatch_fingerprint")) == admission_identity
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


def _default_verify_claim(
    *,
    project_file: str | None,
    workspace_num: int | None,
    pid: int | None,
) -> bool:
    return successor_holds_claim(
        project_file=project_file, workspace_num=workspace_num, pid=pid
    )
