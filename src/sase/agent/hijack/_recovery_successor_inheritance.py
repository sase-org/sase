"""Inheritance checks and acknowledgement file effects."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.hijack._recovery_successor_common import (
    BOOTSTRAP_ACK_SCHEMA_VERSION,
    RECOVERY_ACK_FILENAME,
    RecoveryInheritanceError,
    RecoveryLineage,
    ensure_no_verdict_carryover,
    require_narrowed_permission,
)


def require_recovery_inheritance(
    *,
    predecessor_goal: str | None,
    successor_goal: str | None,
    predecessor_bead: str | None,
    successor_bead: str | None,
    baseline_inherited: bool,
    baseline_diagnostics: Sequence[str] = (),
    predecessor_repo_count: int = 0,
    transferred_repo_count: int = 0,
    repo_diagnostics: Sequence[str] = (),
    predecessor_autonomy: Mapping[str, Any] | None = None,
    predecessor_name: str | None = None,
    explicit_autonomy_selection: str | None = None,
    parent_meta: Mapping[str, Any] | None = None,
    child_meta: Mapping[str, Any] | None = None,
    predecessor_inventory_missing: bool = False,
    launch_identity: str | None = None,
    successor_name: str | None = None,
    process_token: str | None = None,
    project: str | None = None,
    workspace_num: int | None = None,
    workspace_dir: str | None = None,
    lineage: Mapping[str, Any] | RecoveryLineage | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    concrete_target: str | None = None,
) -> dict[str, Any]:
    """Validate every required recovery transfer before provider execution.

    Returns an acknowledgement dict the CAS transaction can observe (and
    persist via :meth:`write_recovery_ack`). Any missing evidence or failed
    inheritance raises :class:`RecoveryInheritanceError` so the record can
    return to held with no partially privileged successor running.

    A predecessor with no bead has no bead to transfer: *successor_bead* must
    then also be empty. Permission scope narrows through the host-composed
    autonomy inheritance only -- an unreadable predecessor record or a
    widening refusal fails closed instead of adopting ambient defaults.

    *predecessor_inventory_missing* fails closed when the predecessor's
    opened-repository inventory could not be read: a missing inventory must
    never pass as an empty one. The optional identity arguments
    (*launch_identity* through *concrete_target*) bind the acknowledgement
    to the durable reservation (mirroring the core
    ``AgentHijackBootstrapAckWire`` shape) so settlement can observe launch
    identity, model, workspace, and lineage evidence instead of a bare
    parent-side synthesis.
    """
    if predecessor_inventory_missing:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor's opened-repository inventory; "
            "a missing inventory must not pass as an empty one"
        )
    if not (isinstance(predecessor_goal, str) and predecessor_goal.strip()):
        raise RecoveryInheritanceError("recovery requires the predecessor's bound goal")
    if successor_goal != predecessor_goal:
        raise RecoveryInheritanceError(
            "recovery requires the host to bind the same goal "
            f"(predecessor {predecessor_goal!r}, successor {successor_goal!r})"
        )
    if predecessor_bead is not None and str(predecessor_bead).strip():
        if successor_bead != predecessor_bead:
            raise RecoveryInheritanceError(
                "recovery requires transfer of the predecessor's bead claim "
                f"(predecessor {predecessor_bead!r}, successor {successor_bead!r})"
            )
    elif successor_bead is not None and str(successor_bead).strip():
        raise RecoveryInheritanceError(
            "recovery successor claims a bead the predecessor never held "
            f"({successor_bead!r})"
        )
    baseline_problems = list(baseline_diagnostics or [])
    if not baseline_inherited:
        baseline_problems.append(
            "commit-finalizer baseline was not inherited from the predecessor"
        )
    if baseline_problems:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor's finalizer baseline: "
            + "; ".join(baseline_problems)
        )
    repo_problems = list(repo_diagnostics or [])
    if transferred_repo_count != predecessor_repo_count:
        repo_problems.append(
            f"transferred {transferred_repo_count} of "
            f"{predecessor_repo_count} opened-repository obligations"
        )
    if repo_problems:
        raise RecoveryInheritanceError(
            "recovery requires all opened-repository obligations: "
            + "; ".join(repo_problems)
        )
    inherited_permission = require_narrowed_permission(
        predecessor_autonomy=predecessor_autonomy,
        predecessor_name=predecessor_name,
        explicit_autonomy_selection=explicit_autonomy_selection,
    )
    ensure_no_verdict_carryover(parent_meta=parent_meta, child_meta=child_meta)
    return build_bootstrap_ack(
        goal=predecessor_goal,
        bead=predecessor_bead,
        baseline_inherited=True,
        transferred_repos=transferred_repo_count,
        permission=inherited_permission,
        launch_identity=launch_identity,
        successor_name=successor_name,
        process_token=process_token,
        project=project,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        lineage=lineage,
        provider=provider,
        model=model,
        effort=effort,
        concrete_target=concrete_target,
    )


def build_bootstrap_ack(
    *,
    goal: str | None,
    bead: str | None,
    baseline_inherited: bool,
    transferred_repos: int,
    permission: Mapping[str, Any],
    launch_identity: str | None = None,
    successor_name: str | None = None,
    process_token: str | None = None,
    project: str | None = None,
    workspace_num: int | None = None,
    workspace_dir: str | None = None,
    lineage: Mapping[str, Any] | RecoveryLineage | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    concrete_target: str | None = None,
) -> dict[str, Any]:
    """Build the versioned bootstrap acknowledgement.

    The shape mirrors the core ``AgentHijackBootstrapAckWire`` (schema
    version :data:`BOOTSTRAP_ACK_SCHEMA_VERSION`): the inherited goal, bead,
    baseline, repository, and permission evidence bound to the durable
    launch identity, successor name, process token, project/workspace pair,
    lineage, and effective provider/model/effort. Persist it with
    :func:`write_recovery_ack` only after every required bootstrap effect
    has finished; settlement observes this evidence instead of a bare
    parent-side synthesis.
    """
    if isinstance(lineage, RecoveryLineage):
        lineage_payload: dict[str, str] | str = lineage.as_dict()
    elif isinstance(lineage, Mapping):
        lineage_payload = dict(lineage)
    else:
        lineage_payload = {}
    return {
        "schema_version": BOOTSTRAP_ACK_SCHEMA_VERSION,
        "goal": goal,
        "bead": bead,
        "baseline_inherited": bool(baseline_inherited),
        "transferred_repos": int(transferred_repos),
        "permission": dict(permission),
        "goal_verified": True,
        "bead_verified": True,
        "scope_verified": True,
        "baselines_verified": bool(baseline_inherited),
        "inventory_verified": True,
        "launch_identity": launch_identity,
        "successor_name": successor_name,
        "process_token": process_token,
        "project": project,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "lineage": lineage_payload,
        "provider": provider,
        "model": model,
        "effort": effort,
        "concrete_target": concrete_target,
    }


def write_recovery_ack(artifacts_dir: str, ack: Mapping[str, Any]) -> str:
    """Persist the inheritance acknowledgement for the CAS transaction."""
    path = Path(artifacts_dir).expanduser() / RECOVERY_ACK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{RECOVERY_ACK_FILENAME}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(dict(ack), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    return str(path)


def read_recovery_ack(artifacts_dir: str) -> dict[str, Any] | None:
    """Return the staged acknowledgement, or ``None`` when absent."""
    path = Path(artifacts_dir).expanduser() / RECOVERY_ACK_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def rollback_recovery_preparation(*, artifacts_dir: str | None) -> bool:
    """Roll back a failed preparation so the record can return to held.

    Preparation itself performs no spawn and holds no workspace claim: the
    transfer completes only inside a successful spawn. Rollback removes any
    staged acknowledgement so a partially prepared successor leaves no live
    or queued duplicate behind. Returns whether an ack file was removed.
    """
    if not artifacts_dir:
        return False
    try:
        path = Path(artifacts_dir).expanduser() / RECOVERY_ACK_FILENAME
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True
