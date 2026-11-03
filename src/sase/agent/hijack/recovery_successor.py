"""Strict recovery successor preparation and mandatory inheritance.

Phase ``strict_successor`` seam for keep-work recovery: a hijacked agent's
successor must launch in the held workspace (the same positive workspace
number **and** directory) with the predecessor's goal, bead claim, commit
finalizer baseline, opened-repository obligations, and permission scope
transferred and validated **before** any provider executes.

The recovery executor (phase ``resolution_launch``) drives these helpers:
:meth:`prepare_recovery_successor` resolves the exact reserved agent-session
member (preserving solo-agent promotion through the shared attach resolver)
and builds the child environment; :meth:`require_recovery_inheritance`
validates every required transfer and returns an acknowledgement dict the
CAS transaction can observe; :meth:`spawn_recovery_successor` performs the
strict spawn with no workspace fallback. A partially prepared successor that
fails validation never reaches the provider: preparation raises
:class:`RecoveryInheritanceError` and :meth:`rollback_recovery_preparation`
removes any staged acknowledgement so the record can return to held with no
live or queued duplicate.

Rust owns recovery policy; this module owns Python effects and validation.
No parallel Python state machine or fallback launcher lives here: spawning
delegates to :func:`sase.agent.detached_child.spawn_agent_session_successor`,
and permission narrowing reuses the host-composed autonomy inheritance in
:mod:`sase.axe.run_agent_directive_metadata_build`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Environment variable carrying the JSON-encoded recovery lineage. The
#: child boot persists it into ``agent_meta.json`` as ``recovery_lineage``.
RECOVERY_LINEAGE_ENV = "SASE_HIJACK_RECOVERY_LINEAGE"

#: Environment marker requesting strict recovery boot semantics: the commit
#: finalizer baseline must be inherited (never freshly captured) and any
#: opened-repository inheritance diagnostic fails the boot.
RECOVERY_STRICT_ENV = "SASE_HIJACK_RECOVERY_STRICT"

#: Filename of the staged inheritance acknowledgement inside a successor's
#: artifacts directory. The CAS transaction observes it before confirming
#: the resolved recovery.
RECOVERY_ACK_FILENAME = "hijack_recovery_ack.json"

#: ``agent_meta.json`` keys that stay with their original turn. Verification
#: receipts and provider declarations are never copied to a successor: a
#: prepared child meta carrying a predecessor's values for these keys is a
#: preparation bug, not an inheritance.
NON_INHERITABLE_VERDICT_KEYS = (
    "outcome",
    "done",
    "receipts",
    "verdict_receipts",
    "declarations",
    "finalizer_declarations",
)


class RecoveryInheritanceError(RuntimeError):
    """A required recovery transfer failed validation before execution."""


@dataclass(frozen=True)
class RecoveryLineage:
    """Durable identity linking a recovery successor to its hijack."""

    hijack_id: str
    from_rung: str
    to_rung: str
    predecessor: str

    def as_dict(self) -> dict[str, str]:
        """Return the ``agent_meta.json`` payload for this lineage."""
        return {
            "hijack_id": self.hijack_id,
            "from_rung": self.from_rung,
            "to_rung": self.to_rung,
            "predecessor": self.predecessor,
        }


def _normalize_recovery_lineage(
    lineage: RecoveryLineage | Mapping[str, Any],
) -> RecoveryLineage:
    """Validate *lineage* and return it as a :class:`RecoveryLineage`."""
    if isinstance(lineage, RecoveryLineage):
        payload = lineage.as_dict()
    elif isinstance(lineage, Mapping):
        payload = dict(lineage)
    else:
        raise RecoveryInheritanceError(
            f"recovery lineage must be a mapping, got {type(lineage).__name__}"
        )
    missing = [
        key
        for key in ("hijack_id", "from_rung", "to_rung", "predecessor")
        if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
    ]
    if missing:
        raise RecoveryInheritanceError(
            f"recovery lineage is missing required fields: {', '.join(missing)}"
        )
    return RecoveryLineage(
        hijack_id=str(payload["hijack_id"]).strip(),
        from_rung=str(payload["from_rung"]).strip(),
        to_rung=str(payload["to_rung"]).strip(),
        predecessor=str(payload["predecessor"]).strip(),
    )


def _encode_recovery_lineage(lineage: RecoveryLineage | Mapping[str, Any]) -> str:
    """Encode *lineage* for transport in the successor environment."""
    return json.dumps(_normalize_recovery_lineage(lineage).as_dict(), sort_keys=True)


def decode_recovery_lineage(raw: str | None) -> RecoveryLineage:
    """Decode a lineage payload, raising on missing or malformed input."""
    if not isinstance(raw, str) or not raw.strip():
        raise RecoveryInheritanceError(
            f"recovery requires a lineage payload ({RECOVERY_LINEAGE_ENV} is missing)"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryInheritanceError(
            f"recovery lineage payload is not valid JSON: {exc}"
        ) from exc
    return _normalize_recovery_lineage(payload)


def _recovery_child_env(lineage: RecoveryLineage | Mapping[str, Any]) -> dict[str, str]:
    """Return the environment delta a recovery successor boots with."""
    return {
        RECOVERY_LINEAGE_ENV: _encode_recovery_lineage(lineage),
        RECOVERY_STRICT_ENV: "1",
    }


def _validate_recovery_workspace_pair(
    *,
    project_name: str,
    workspace_num: object,
    workspace_dir: object,
) -> None:
    """Require the exact positive workspace pair, raising on any deviation.

    Foreign owners, workspace ``#0``, pool workspaces, and metadata where the
    number and directory disagree are all rejected here, before spawn.
    """
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise RecoveryInheritanceError(
            "recovery requires the held positive workspace number, "
            f"got {workspace_num!r}"
        )
    if not isinstance(workspace_dir, str) or not workspace_dir.strip():
        raise RecoveryInheritanceError(
            f"recovery requires the held workspace directory, got {workspace_dir!r}"
        )
    try:
        from sase.running_field import get_workspace_directory_for_num
    except ImportError:
        return
    try:
        canonical_dir, _ = get_workspace_directory_for_num(
            workspace_num,
            project_name,
            clean=False,
        )
    except (RuntimeError, OSError, ValueError):
        return
    if os.path.normpath(canonical_dir) != os.path.normpath(workspace_dir):
        raise RecoveryInheritanceError(
            f"recovery workspace metadata mismatch: workspace #{workspace_num} "
            f"resolves to {canonical_dir}, not {workspace_dir}"
        )


def _ensure_no_verdict_carryover(
    *,
    parent_meta: Mapping[str, Any] | None,
    child_meta: Mapping[str, Any] | None,
) -> None:
    """Reject a successor meta that copied the predecessor's verdicts.

    Verification receipts and provider declarations stay with their original
    turn; the successor proves its own work from the inherited baseline.
    """
    if not isinstance(parent_meta, Mapping) or not isinstance(child_meta, Mapping):
        return
    carried = [
        key
        for key in NON_INHERITABLE_VERDICT_KEYS
        if key in child_meta
        and parent_meta.get(key) is not None
        and child_meta[key] == parent_meta[key]
    ]
    if carried:
        raise RecoveryInheritanceError(
            "recovery successor must not copy predecessor verdicts: "
            + ", ".join(sorted(carried))
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
    """
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
    inherited_permission = _require_narrowed_permission(
        predecessor_autonomy=predecessor_autonomy,
        predecessor_name=predecessor_name,
        explicit_autonomy_selection=explicit_autonomy_selection,
    )
    _ensure_no_verdict_carryover(parent_meta=parent_meta, child_meta=child_meta)
    return {
        "schema_version": 1,
        "goal": predecessor_goal,
        "bead": predecessor_bead,
        "baseline_inherited": True,
        "transferred_repos": transferred_repo_count,
        "permission": inherited_permission,
    }


def _require_narrowed_permission(
    *,
    predecessor_autonomy: Mapping[str, Any] | None,
    predecessor_name: str | None,
    explicit_autonomy_selection: str | None,
) -> dict[str, Any]:
    """Inherit the predecessor's permission scope without widening."""
    if not isinstance(predecessor_autonomy, Mapping) or not predecessor_autonomy:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor's live permission record; "
            "an unreadable predecessor must not let the successor adopt a "
            "wider ambient policy"
        )
    from sase.autonomy.record import autonomy_inherit_record

    try:
        outcome = autonomy_inherit_record(
            dict(predecessor_autonomy),
            predecessor_name=str(predecessor_name or "unknown predecessor"),
            explicit_selection=explicit_autonomy_selection,
            actor_kind="host",
        )
    except Exception as exc:
        raise RecoveryInheritanceError(
            f"recovery permission inheritance failed: {exc}"
        ) from exc
    if not isinstance(outcome, dict) or not isinstance(outcome.get("record"), dict):
        raise RecoveryInheritanceError(
            "recovery permission inheritance produced no record"
        )
    if outcome.get("status") == "refused":
        raise RecoveryInheritanceError(
            "recovery permission inheritance refused widening: "
            f"{outcome.get('reason', 'unknown reason')}"
        )
    return dict(outcome["record"])


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


def prepare_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    resolve_plan: Any | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[Any, dict[str, str]]:
    """Resolve the exact reserved session member for a recovery successor.

    The shared agent-session attach resolver performs the resolution, so a
    solo-agent predecessor is promoted exactly as a normal follow-up would
    be. The workspace pair is validated before resolution; any deviation
    raises :class:`RecoveryInheritanceError`. Returns the resolved plan and
    the child environment delta (lineage plus the strict-boot marker).
    """
    resolved_lineage = _normalize_recovery_lineage(lineage)
    _validate_recovery_workspace_pair(
        project_name=project_name,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
    )
    from sase.agent import _agent_session_attach_resolution as _resolution

    resolve = resolve_plan or _resolution.resolve_agent_session_attach_plan
    plan = resolve(directive, project_name=project_name)
    env: dict[str, str] = _recovery_child_env(resolved_lineage)
    if extra_env:
        env.update(dict(extra_env))
    return plan, env


def spawn_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    cl_name: str | None = None,
    agent_session_role: str | None = None,
    vcs_ref: tuple[str, str] | None = None,
    timestamp: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    spawn_fn: Any | None = None,
    resolve_plan: Any | None = None,
) -> Any:
    """Spawn a recovery successor on the exact held workspace pair.

    A narrow seam over
    :func:`sase.agent.detached_child.spawn_agent_session_successor`: one
    resolution (reused for the spawn so the reserved member cannot drift),
    one transfer-or-fresh-claim on the same pair, no pool or ``#0``
    fallback. Workspace or lineage validation failures raise
    :class:`RecoveryInheritanceError` before any spawn is attempted.
    """
    from sase.agent.detached_child import spawn_agent_session_successor

    plan, prepared_env = prepare_recovery_successor(
        directive,
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        lineage=lineage,
        resolve_plan=resolve_plan,
        extra_env=extra_env,
    )
    merged_env = dict(prepared_env)
    if extra_env:
        merged_env.update(dict(extra_env))
    return spawn_agent_session_successor(
        directive,
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name or plan.agent_name,
        agent_session_role=agent_session_role,
        vcs_ref=vcs_ref,
        timestamp=timestamp,
        extra_env=merged_env,
        spawn_fn=spawn_fn,
        resolve_plan=lambda *args, **kwargs: plan,
    )


__all__ = [
    "NON_INHERITABLE_VERDICT_KEYS",
    "RECOVERY_ACK_FILENAME",
    "RECOVERY_LINEAGE_ENV",
    "RECOVERY_STRICT_ENV",
    "RecoveryInheritanceError",
    "RecoveryLineage",
    "decode_recovery_lineage",
    "prepare_recovery_successor",
    "read_recovery_ack",
    "require_recovery_inheritance",
    "rollback_recovery_preparation",
    "spawn_recovery_successor",
    "write_recovery_ack",
]
