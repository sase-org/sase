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
#: ``hijack_lineage`` is the established canonical key the escalation walk
#: and recovery preview read; new boots write both keys with the same payload
#: while the mixed naming is audited out (see ``_apply_recovery_lineage``).
RECOVERY_LINEAGE_ENV = "SASE_HIJACK_RECOVERY_LINEAGE"

#: Canonical lineage key in ``agent_meta.json``. The escalation target walk
#: and recovery preview read this key; the child boot writes it alongside
#: the historical ``recovery_lineage`` alias so either reader observes the
#: same ``{hijack_id, from_rung, to_rung, predecessor}`` payload.
HIJACK_LINEAGE_META_KEY = "hijack_lineage"

#: Historical lineage key in ``agent_meta.json``. Kept as an alias of
#: :data:`HIJACK_LINEAGE_META_KEY` until every reader is audited.
RECOVERY_LINEAGE_META_KEY = "recovery_lineage"

#: Environment variable carrying the JSON-encoded reservation descriptor for
#: a strict recovery successor. The executor binds one validated descriptor
#: per CAS reservation; the child boot decodes it before provider execution
#: and fails closed when it is missing or malformed.
RECOVERY_DESCRIPTOR_ENV = "SASE_HIJACK_RECOVERY_DESCRIPTOR"

#: Wire schema version for the bootstrap ack and reservation descriptor.
#: Mirrors ``AGENT_HIJACK_EXECUTION_WIRE_SCHEMA_VERSION`` in
#: ``sase_core::agent_hijack::execution``; Python owns the file effects, the
#: core owns the confirmation/rollback decisions that consume these shapes.
BOOTSTRAP_ACK_SCHEMA_VERSION = 1

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


class RecoveryBootstrapError(RecoveryInheritanceError):
    """A typed bootstrap stop before provider execution.

    The child boot raises this (instead of a bare
    :class:`RecoveryInheritanceError`) when the reservation descriptor or any
    required inheritance step fails, so the runner can record a
    machine-readable ``code`` alongside the message. ``code`` names the
    failed step (``missing_descriptor``, ``identity_mismatch``,
    ``goal_mismatch``, ``bead_mismatch``, ``scope_missing``,
    ``baseline_mismatch``, ``inventory_mismatch``, ``model_mismatch``); the
    provider is never invoked after this raises.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
    inherited_permission = _require_narrowed_permission(
        predecessor_autonomy=predecessor_autonomy,
        predecessor_name=predecessor_name,
        explicit_autonomy_selection=explicit_autonomy_selection,
    )
    _ensure_no_verdict_carryover(parent_meta=parent_meta, child_meta=child_meta)
    return _build_bootstrap_ack(
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


def _build_bootstrap_ack(
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


def build_recovery_descriptor(
    *,
    hijack_id: str,
    launch_identity: str,
    concrete_target: str,
    reserved_successor_name: str,
    project: str,
    workspace_dir: str,
    lineage: Mapping[str, Any] | RecoveryLineage,
    reserved_member: str = "",
    attach_plan: str = "",
    admission_request_id: str | None = None,
    admission_identity: str | None = None,
    workspace_num: int | None = None,
    expected_owner_pid: int | None = None,
    resolver_pid: int | None = None,
    resolver_process_identity_token: str | None = None,
    prompt_digest: str = "",
    attempt_revision: int = 0,
) -> dict[str, Any]:
    """Build one validated descriptor for a CAS reservation.

    The shape mirrors the core ``AgentHijackAdmissionDescriptorWire``:
    the prepared prompt digest and exact target, the reserved successor
    member/attach plan, the fixed project and workspace pair, the expected
    held owner, lineage, and the attempt identities. The executor persists
    one descriptor per reservation and threads it into the child through
    :data:`RECOVERY_DESCRIPTOR_ENV`; the child boot decodes it with
    :func:`decode_recovery_descriptor` and fails closed when it is missing.
    """
    if isinstance(lineage, RecoveryLineage):
        lineage_payload: str = _encode_recovery_lineage(lineage)
    elif isinstance(lineage, Mapping):
        lineage_payload = _encode_recovery_lineage(lineage)
    else:
        raise RecoveryInheritanceError(
            f"recovery descriptor requires a lineage mapping, got {type(lineage).__name__}"
        )
    return {
        "schema_version": BOOTSTRAP_ACK_SCHEMA_VERSION,
        "hijack_id": hijack_id,
        "launch_identity": launch_identity,
        "admission_request_id": admission_request_id,
        "admission_identity": admission_identity,
        "concrete_target": concrete_target,
        "reserved_successor_name": reserved_successor_name,
        "reserved_member": reserved_member,
        "attach_plan": attach_plan,
        "project": project,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "expected_owner_pid": expected_owner_pid,
        "lineage": lineage_payload,
        "resolver_pid": resolver_pid,
        "resolver_process_identity_token": resolver_process_identity_token,
        "prompt_digest": prompt_digest,
        "attempt_revision": int(attempt_revision),
    }


def encode_recovery_descriptor(descriptor: Mapping[str, Any]) -> str:
    """Encode a reservation descriptor for transport in the child env."""
    return json.dumps(dict(descriptor), sort_keys=True)


def decode_recovery_descriptor(raw: str | None) -> dict[str, Any]:
    """Decode a reservation descriptor, failing closed when absent.

    Raises :class:`RecoveryBootstrapError` when the descriptor is missing,
    malformed, or names no usable reservation, so the child boot stops
    before the provider executes.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise RecoveryBootstrapError(
            "missing_descriptor",
            f"recovery requires the reservation descriptor ({RECOVERY_DESCRIPTOR_ENV} is missing)",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            f"recovery descriptor payload is not valid JSON: {exc}",
        ) from exc
    if not isinstance(payload, Mapping) or not payload:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            "recovery descriptor payload names no reservation",
        )
    descriptor = dict(payload)
    missing = [
        key
        for key in (
            "hijack_id",
            "launch_identity",
            "concrete_target",
            "reserved_successor_name",
            "project",
            "workspace_dir",
            "lineage",
        )
        if not descriptor.get(key)
    ]
    if missing:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            "recovery descriptor is missing required fields: " + ", ".join(missing),
        )
    return descriptor


@dataclass(frozen=True)
class BootstrapObservation:
    """Child-side facts the bootstrap gate proves before provider execution.

    ``parent_repos``/``child_repos`` map opened-repository identities to
    their recorded workspace directories; ``None`` means the inventory could
    not be read (a missing predecessor inventory fails closed and must
    never pass as an empty one). ``parent_baseline``/``child_baseline``
    carry the commit-finalizer fingerprint maps (``None`` when unreadable).
    ``launch_identity`` is the child's own attempt identity from
    ``RECOVERY_LAUNCH_IDENTITY_ENV``. See :func:`collect_bootstrap_observation`.
    """

    successor_name: str | None
    process_token: str | None
    project: str | None
    workspace_num: int | None
    workspace_dir: str | None
    launch_identity: str | None
    provider: str | None
    model: str | None
    effort: str | None
    goal: str | None
    bead: str | None
    predecessor_goal: str | None
    predecessor_bead: str | None
    predecessor_autonomy: Mapping[str, Any] | None
    predecessor_name: str | None
    explicit_autonomy_selection: str | None
    parent_meta: Mapping[str, Any] | None
    child_meta: Mapping[str, Any] | None
    baseline_inherited: bool
    baseline_diagnostics: tuple[str, ...] = ()
    repo_diagnostics: tuple[str, ...] = ()
    predecessor_inventory_missing: bool = False
    parent_repos: Mapping[str, Any] | None = None
    child_repos: Mapping[str, Any] | None = None
    parent_baseline: Mapping[str, Any] | None = None
    child_baseline: Mapping[str, Any] | None = None
    lineage: Mapping[str, Any] | None = None


def collect_bootstrap_observation(
    *,
    child_artifacts_dir: str,
    parent_artifacts_dir: str | None,
    successor_name: str | None,
    process_token: str | None,
    project: str | None,
    workspace_num: int | None,
    workspace_dir: str | None,
    provider: str | None,
    model: str | None,
    effort: str | None,
    explicit_autonomy_selection: str | None = None,
    launch_identity: str | None = None,
) -> BootstrapObservation:
    """Collect the child-side facts the bootstrap gate must prove.

    Reads the predecessor's live ``agent_meta.json`` (goal, bead, permission
    record) and opened-repository inventory through the attach plan's parent
    artifacts directory, plus the child's own freshly written metadata,
    baselines, and inventory. Missing files degrade to ``None`` evidence
    that :func:`enforce_recovery_bootstrap` fails closed on; this function
    itself never raises for absent evidence.
    """
    from sase.history.chat_fork.common import load_json_object

    from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV

    if launch_identity is None:
        raw_launch = os.environ.get(RECOVERY_LAUNCH_IDENTITY_ENV)
        launch_identity = (
            raw_launch if isinstance(raw_launch, str) and raw_launch else None
        )
    parent_meta: Mapping[str, Any] | None = None
    if parent_artifacts_dir:
        loaded_parent = load_json_object(Path(parent_artifacts_dir) / "agent_meta.json")
        if isinstance(loaded_parent, Mapping) and loaded_parent:
            parent_meta = dict(loaded_parent)
    child_meta: Mapping[str, Any] | None = None
    loaded_child = load_json_object(Path(child_artifacts_dir) / "agent_meta.json")
    if isinstance(loaded_child, Mapping) and loaded_child:
        child_meta = dict(loaded_child)
    predecessor_autonomy: Mapping[str, Any] | None = None
    if parent_artifacts_dir:
        try:
            from sase.autonomy.record import live_record

            found = live_record(parent_artifacts_dir)
        except Exception:
            found = None
        if isinstance(found, Mapping) and found:
            predecessor_autonomy = dict(found)
    lineage: Mapping[str, Any] | None = None
    try:
        lineage = decode_recovery_lineage(
            os.environ.get(RECOVERY_LINEAGE_ENV)
        ).as_dict()
    except RecoveryInheritanceError:
        lineage = None
    return BootstrapObservation(
        successor_name=successor_name,
        process_token=process_token,
        project=project,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        launch_identity=launch_identity,
        provider=provider,
        model=model,
        effort=effort,
        goal=_meta_goal_value(child_meta),
        bead=_meta_bead_value(child_meta),
        predecessor_goal=_meta_goal_value(parent_meta),
        predecessor_bead=_meta_bead_value(parent_meta),
        predecessor_autonomy=predecessor_autonomy,
        predecessor_name=_meta_name_value(parent_meta),
        explicit_autonomy_selection=explicit_autonomy_selection,
        parent_meta=parent_meta,
        child_meta=child_meta,
        baseline_inherited=False,
        baseline_diagnostics=(),
        repo_diagnostics=(),
        predecessor_inventory_missing=parent_artifacts_dir is None
        or not Path(str(parent_artifacts_dir)).is_dir(),
        parent_repos=_read_opened_repo_inventory(parent_artifacts_dir),
        child_repos=_read_opened_repo_inventory(child_artifacts_dir),
        parent_baseline=_read_baseline_fingerprints(parent_artifacts_dir),
        child_baseline=_read_baseline_fingerprints(child_artifacts_dir),
        lineage=lineage,
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
        inherited_permission = _require_narrowed_permission(
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
        _ensure_no_verdict_carryover(
            parent_meta=observation.parent_meta, child_meta=child_meta
        )
    except RecoveryInheritanceError as exc:
        raise RecoveryBootstrapError("verdict_carryover", str(exc)) from exc
    ack = _build_bootstrap_ack(
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


def _meta_goal_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the bound goal from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("goal_id", "goal"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _meta_bead_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the bead claim from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("bead_id", "bead"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _meta_name_value(meta: Mapping[str, Any] | None) -> str | None:
    """Read the agent name from an ``agent_meta.json`` payload."""
    if not isinstance(meta, Mapping):
        return None
    for key in ("name", "agent_name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_opened_repo_inventory(
    artifacts_dir: str | None,
) -> dict[str, str] | None:
    """Map opened-repository identities to workspace dirs, ``None`` if unreadable."""
    if not artifacts_dir or not Path(str(artifacts_dir)).is_dir():
        return None
    try:
        from sase._linked_repo_markers import opened_repo_records

        records = opened_repo_records(Path(str(artifacts_dir)))
    except Exception:
        return None
    inventory: dict[str, str] = {}
    for name, record in records.items():
        if not isinstance(record, Mapping):
            continue
        workspace_dir = record.get("workspace_dir")
        inventory[str(name)] = (
            str(workspace_dir) if isinstance(workspace_dir, str) else ""
        )
    return inventory


def _read_baseline_fingerprints(
    artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Load baseline fingerprint maps, ``None`` when unreadable or absent."""
    if not artifacts_dir or not Path(str(artifacts_dir)).is_dir():
        return None
    try:
        from sase.llm_provider.commit_finalizer_baseline import load_dirty_baseline

        found = load_dirty_baseline(Path(str(artifacts_dir)))
    except Exception:
        return None
    if found is None:
        return None
    try:
        return dict(found)
    except (TypeError, ValueError):
        return None


def prepare_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    descriptor: Mapping[str, Any] | None = None,
    resolve_plan: Any | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[Any, dict[str, str]]:
    """Resolve the exact reserved session member for a recovery successor.

    The shared agent-session attach resolver performs the resolution, so a
    solo-agent predecessor is promoted exactly as a normal follow-up would
    be. The workspace pair is validated before resolution; any deviation
    raises :class:`RecoveryInheritanceError`. Returns the resolved plan and
    the child environment delta (lineage, the strict-boot marker, and the
    reservation descriptor when one was bound). The child boot decodes the
    descriptor before provider execution and fails closed when it is
    missing.
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
    if not plan.predecessor_artifacts_dir:
        from dataclasses import replace
        from sase.agent.hijack import ledger

        record = ledger.load_record(resolved_lineage.hijack_id)
        predecessor_dir = record.get("artifacts_dir") if record is not None else None
        if not predecessor_dir and plan.parent_name == resolved_lineage.predecessor:
            predecessor_dir = plan.parent_artifacts_dir
        plan = replace(
            plan,
            predecessor_artifacts_dir=predecessor_dir,
            predecessor_name=resolved_lineage.predecessor,
        )
    env: dict[str, str] = _recovery_child_env(resolved_lineage)
    if descriptor is not None:
        env[RECOVERY_DESCRIPTOR_ENV] = encode_recovery_descriptor(descriptor)
    if extra_env:
        env.update(dict(extra_env))
    return plan, env


def spawn_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    project_file: str | None = None,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    descriptor: Mapping[str, Any] | None = None,
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
    :class:`RecoveryInheritanceError` before any spawn is attempted. A
    reservation descriptor threads into the child environment so its boot
    can prove inheritance before provider execution.
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
        descriptor=descriptor,
        resolve_plan=resolve_plan,
        extra_env=extra_env,
    )
    merged_env = dict(prepared_env)
    if extra_env:
        merged_env.update(dict(extra_env))
    return spawn_agent_session_successor(
        directive,
        project_name=project_name,
        project_file=project_file,
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
    "BOOTSTRAP_ACK_SCHEMA_VERSION",
    "HIJACK_LINEAGE_META_KEY",
    "NON_INHERITABLE_VERDICT_KEYS",
    "RECOVERY_ACK_FILENAME",
    "RECOVERY_DESCRIPTOR_ENV",
    "RECOVERY_LINEAGE_ENV",
    "RECOVERY_LINEAGE_META_KEY",
    "RECOVERY_STRICT_ENV",
    "BootstrapObservation",
    "RecoveryBootstrapError",
    "RecoveryInheritanceError",
    "RecoveryLineage",
    "build_recovery_descriptor",
    "collect_bootstrap_observation",
    "decode_recovery_descriptor",
    "decode_recovery_lineage",
    "encode_recovery_descriptor",
    "enforce_recovery_bootstrap",
    "prepare_recovery_successor",
    "read_recovery_ack",
    "require_recovery_inheritance",
    "rollback_recovery_preparation",
    "spawn_recovery_successor",
    "write_recovery_ack",
]
