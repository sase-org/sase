"""Validate child-side recovery inheritance before provider execution."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack._recovery_successor_bootstrap_observation import (
    BootstrapObservation,
)
from sase.agent.hijack._recovery_successor_common import (
    RecoveryBootstrapError,
    RecoveryInheritanceError,
    ensure_no_verdict_carryover,
    require_narrowed_permission,
)
from sase.agent.hijack._recovery_successor_descriptor import (
    decode_recovery_descriptor,
    encode_recovery_descriptor,
)
from sase.agent.hijack._recovery_successor_inheritance import (
    build_bootstrap_ack,
    write_recovery_ack,
)


def enforce_recovery_bootstrap(
    *,
    child_artifacts_dir: str,
    descriptor: Mapping[str, Any],
    observation: BootstrapObservation,
) -> dict[str, Any]:
    """Prove required inheritance in the child before provider execution.

    Validates the reservation descriptor, then the attempt identity, goal,
    bead claim, permission scope, baseline fingerprints, repository
    identities, and effective model/effort against it. Persists the
    versioned ack via :func:`write_recovery_ack` only after every check
    holds and returns it. Raises :class:`RecoveryBootstrapError` (with a
    machine-readable ``code``) on the first failure; the caller must not
    invoke the provider afterwards.
    """
    resolved = decode_recovery_descriptor(
        encode_recovery_descriptor(descriptor)
        if isinstance(descriptor, Mapping)
        else None
    )
    _require_bootstrap_identity(resolved, observation)
    _require_bootstrap_goal(observation)
    _require_bootstrap_bead(observation)
    try:
        inherited_permission = require_narrowed_permission(
            predecessor_autonomy=observation.predecessor_autonomy,
            predecessor_name=observation.predecessor_name,
            explicit_autonomy_selection=observation.explicit_autonomy_selection,
        )
    except RecoveryInheritanceError as exc:
        raise RecoveryBootstrapError("scope_missing", str(exc)) from exc
    transferred = _require_bootstrap_inventory(observation)
    _require_bootstrap_baseline(observation)
    effective_target = _require_bootstrap_model(resolved, observation)
    provider, model, effort = _split_concrete_target(effective_target)
    child_meta = (
        observation.child_meta if isinstance(observation.child_meta, Mapping) else {}
    )
    try:
        ensure_no_verdict_carryover(
            parent_meta=observation.parent_meta, child_meta=child_meta
        )
    except RecoveryInheritanceError as exc:
        raise RecoveryBootstrapError("verdict_carryover", str(exc)) from exc
    ack = build_bootstrap_ack(
        goal=observation.predecessor_goal,
        bead=observation.predecessor_bead,
        baseline_inherited=True,
        transferred_repos=transferred,
        permission=inherited_permission,
        launch_identity=resolved.get("launch_identity"),
        successor_name=observation.successor_name,
        process_token=observation.process_token,
        project=observation.project,
        workspace_num=observation.workspace_num,
        workspace_dir=observation.workspace_dir,
        lineage=observation.lineage,
        provider=provider,
        model=model,
        effort=effort,
        concrete_target=effective_target,
    )
    write_recovery_ack(child_artifacts_dir, ack)
    return ack


def _require_bootstrap_identity(
    descriptor: Mapping[str, Any], observation: BootstrapObservation
) -> None:
    """Prove the child is the reservation's exact attempt."""
    if not observation.launch_identity or (
        observation.launch_identity != descriptor.get("launch_identity")
    ):
        raise RecoveryBootstrapError(
            "identity_mismatch",
            "recovery requires the child's launch identity to match the "
            f"reservation ({observation.launch_identity!r} != "
            f"{descriptor.get('launch_identity')!r})",
        )
    if not observation.successor_name or (
        observation.successor_name != descriptor.get("reserved_successor_name")
    ):
        raise RecoveryBootstrapError(
            "identity_mismatch",
            "recovery requires the reserved successor identity "
            f"({observation.successor_name!r} != "
            f"{descriptor.get('reserved_successor_name')!r})",
        )
    if not observation.project or observation.project != descriptor.get("project"):
        raise RecoveryBootstrapError(
            "workspace_mismatch",
            "recovery requires the held project "
            f"({observation.project!r} != {descriptor.get('project')!r})",
        )
    if not observation.workspace_dir or not _same_path(
        observation.workspace_dir, descriptor.get("workspace_dir")
    ):
        raise RecoveryBootstrapError(
            "workspace_mismatch",
            "recovery requires the exact held workspace directory "
            f"({observation.workspace_dir!r} != {descriptor.get('workspace_dir')!r})",
        )
    expected_num = descriptor.get("workspace_num")
    if not isinstance(observation.workspace_num, int) or observation.workspace_num <= 0:
        raise RecoveryBootstrapError(
            "workspace_mismatch",
            "recovery requires the held positive workspace number, "
            f"got {observation.workspace_num!r}",
        )
    if (
        isinstance(expected_num, int)
        and expected_num > 0
        and observation.workspace_num != expected_num
    ):
        raise RecoveryBootstrapError(
            "workspace_mismatch",
            "recovery requires the held workspace number "
            f"({observation.workspace_num!r} != {expected_num!r})",
        )
    expected_lineage = _decode_lineage_payload(descriptor.get("lineage"))
    if not isinstance(observation.lineage, Mapping) or not observation.lineage:
        raise RecoveryBootstrapError(
            "identity_mismatch",
            "recovery requires the reservation lineage in the child boot",
        )
    if dict(observation.lineage) != dict(expected_lineage):
        raise RecoveryBootstrapError(
            "identity_mismatch",
            "recovery lineage does not match the reservation "
            f"({dict(observation.lineage)!r} != {dict(expected_lineage)!r})",
        )


def _require_bootstrap_goal(observation: BootstrapObservation) -> None:
    """Prove the child bound the predecessor's goal (not a caller value)."""
    if not (
        isinstance(observation.predecessor_goal, str)
        and observation.predecessor_goal.strip()
    ):
        raise RecoveryBootstrapError(
            "goal_mismatch", "recovery requires the predecessor's bound goal"
        )
    if observation.goal != observation.predecessor_goal:
        raise RecoveryBootstrapError(
            "goal_mismatch",
            "recovery requires the host to bind the same goal "
            f"(predecessor {observation.predecessor_goal!r}, "
            f"successor {observation.goal!r})",
        )


def _require_bootstrap_bead(observation: BootstrapObservation) -> None:
    """Prove the child's bead claim matches the predecessor's (or its lack)."""
    predecessor_bead = observation.predecessor_bead
    if predecessor_bead is not None and str(predecessor_bead).strip():
        if observation.bead != predecessor_bead:
            raise RecoveryBootstrapError(
                "bead_mismatch",
                "recovery requires transfer of the predecessor's bead claim "
                f"(predecessor {predecessor_bead!r}, successor {observation.bead!r})",
            )
    elif observation.bead is not None and str(observation.bead).strip():
        raise RecoveryBootstrapError(
            "bead_mismatch",
            "recovery successor claims a bead the predecessor never held "
            f"({observation.bead!r})",
        )


def _require_bootstrap_baseline(observation: BootstrapObservation) -> None:
    """Prove the child's baseline fingerprints equal the predecessor's."""
    problems = list(observation.baseline_diagnostics or [])
    if observation.parent_baseline is None:
        problems.append("predecessor baseline fingerprints are not observable")
    if observation.child_baseline is None:
        problems.append("successor baseline fingerprints are not observable")
    if (
        observation.parent_baseline is not None
        and observation.child_baseline is not None
        and dict(observation.child_baseline) != dict(observation.parent_baseline)
    ):
        problems.append(
            "successor baseline fingerprints diverged from the predecessor; "
            "a fresh snapshot of the predecessor's dirty tree is never allowed"
        )
    if problems:
        raise RecoveryBootstrapError(
            "baseline_mismatch",
            "recovery requires the predecessor's finalizer baseline: "
            + "; ".join(problems),
        )


def _require_bootstrap_inventory(observation: BootstrapObservation) -> int:
    """Prove every opened-repository obligation transferred by identity."""
    if observation.predecessor_inventory_missing or observation.parent_repos is None:
        raise RecoveryBootstrapError(
            "inventory_mismatch",
            "recovery requires the predecessor's opened-repository inventory; "
            "a missing inventory must not pass as an empty one",
        )
    if observation.child_repos is None:
        raise RecoveryBootstrapError(
            "inventory_mismatch",
            "recovery requires the successor's opened-repository inventory",
        )
    parent = dict(observation.parent_repos)
    child = dict(observation.child_repos)
    problems: list[str] = list(observation.repo_diagnostics or [])
    missing = sorted(name for name in parent if name not in child)
    if missing:
        problems.append("missing opened-repository obligations: " + ", ".join(missing))
    extra = sorted(name for name in child if name not in parent)
    if extra:
        problems.append("unexpected opened-repository obligations: " + ", ".join(extra))
    moved = sorted(
        name for name in parent if name in child and child[name] != parent[name]
    )
    if moved:
        problems.append("opened-repository workspace moved: " + ", ".join(moved))
    if problems:
        raise RecoveryBootstrapError(
            "inventory_mismatch",
            "recovery requires all opened-repository obligations: "
            + "; ".join(problems),
        )
    return len(parent)


def _require_bootstrap_model(
    descriptor: Mapping[str, Any], observation: BootstrapObservation
) -> str:
    """Prove the child's effective model equals the pinned target."""
    from sase.agent.hijack.recover_target import require_concrete_target
    from sase.agent.hijack.recover_common import RecoveryRefusal

    pinned = descriptor.get("concrete_target")
    if not isinstance(pinned, str) or not pinned.strip():
        raise RecoveryBootstrapError(
            "model_mismatch", "recovery descriptor names no pinned target"
        )
    base = (observation.model or "").strip()
    if not base:
        raise RecoveryBootstrapError(
            "model_mismatch", "recovery successor reports no effective model"
        )
    embedded_effort: str | None = None
    if "@" in base and "/" in base.rpartition("@")[0]:
        stem, _, maybe_effort = base.rpartition("@")
        if _is_known_effort(maybe_effort):
            base, embedded_effort = stem, maybe_effort
    candidate = f"{(observation.provider or '').strip()}/{base}"
    effort = (
        str(observation.effort).strip()
        if observation.effort and str(observation.effort).strip()
        else (embedded_effort or "")
    )
    if effort:
        candidate += f"@{effort}"
    try:
        effective = require_concrete_target(candidate, source="successor bootstrap")
        expected = require_concrete_target(pinned, source="reservation descriptor")
    except RecoveryRefusal as exc:
        raise RecoveryBootstrapError("model_mismatch", str(exc)) from exc
    if effective != expected:
        expected_effort = expected.rpartition("@")[2] if "@" in expected else ""
        effective_effort = effective.rpartition("@")[2] if "@" in effective else ""
        detail = (
            f" (effort {effective_effort!r} != {expected_effort!r})"
            if expected_effort or effective_effort
            else ""
        )
        raise RecoveryBootstrapError(
            "model_mismatch",
            f"recovery requires the pinned effective model ({effective!r} != "
            f"{expected!r}){detail}",
        )
    return effective


def _is_known_effort(value: str) -> bool:
    """Return whether *value* is a known ``@effort`` suffix."""
    try:
        from sase.macro.effort import EFFORT_LEVELS
    except Exception:
        return False
    return value in EFFORT_LEVELS


def _split_concrete_target(value: str) -> tuple[str | None, str, str | None]:
    """Split a concrete ``provider/model[@effort]`` into its parts."""
    stem, _, effort = value.rpartition("@") if "@" in value else (value, "", "")
    provider, _, model = stem.partition("/")
    return (provider or None, model, effort or None)


def _decode_lineage_payload(raw: Any) -> dict[str, Any]:
    """Decode a descriptor lineage payload, returning ``{}`` when unusable."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _same_path(left: Any, right: Any) -> bool:
    """Return whether two workspace directories name the same path."""
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if not left.strip() or not right.strip():
        return False
    return os.path.normpath(left) == os.path.normpath(right)
