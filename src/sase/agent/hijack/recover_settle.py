"""Idempotent recovery settlement and inheritance evidence gathering."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import (
    InheritanceEvidence,
    RecoverySubject,
    RecoveryRefusal,
    clean_string,
)
from sase.agent.hijack.recover_subject import read_predecessor_done_marker


def gather_recovery_inheritance(
    subject: RecoverySubject,
    successor_artifacts_dir: str | None,
    *,
    goal: str | None = None,
    bead: str | None = None,
    explicit_autonomy_selection: str | None = None,
) -> InheritanceEvidence | None:
    """Gather observable inheritance evidence, or ``None`` when not ready.

    ``None`` means the successor has not booted far enough to observe (its
    ``agent_meta.json`` is absent): the caller retains ``resolving`` and
    lets reconciliation retry rather than failing a live child to ``held``.
    Present-but-invalid evidence raises through
    :func:`require_recovery_inheritance` at validation time.

    The proof always comes from the observed metadata: the predecessor's
    ``agent_meta.json`` and the child's. Caller-supplied *goal*/*bead*
    values are expectations, not proof -- when given they must equal the
    observed child values or this raises instead of substituting for them.
    """
    from sase.history.chat_fork.common import load_json_object

    from sase.agent.hijack.recovery_successor import RecoveryInheritanceError

    record = subject.record
    predecessor_meta = subject.predecessor_meta
    child_meta: Mapping[str, Any] = {}
    if successor_artifacts_dir:
        loaded = load_json_object(Path(successor_artifacts_dir) / "agent_meta.json")
        if isinstance(loaded, Mapping) and loaded:
            child_meta = dict(loaded)
    if not child_meta:
        return None
    predecessor_dir = clean_string(record.get("artifacts_dir"))
    predecessor_bead = clean_string(predecessor_meta.get("bead_id"))
    successor_bead = clean_string(child_meta.get("bead_id"))
    if bead is not None and clean_string(bead) != successor_bead:
        raise RecoveryInheritanceError(
            "recovery requires the observed bead claim to match the expected "
            f"claim (expected {clean_string(bead)!r}, observed {successor_bead!r})"
        )
    predecessor_goal = _meta_goal(predecessor_meta)
    successor_goal = _meta_goal(child_meta)
    if goal is not None and clean_string(goal) != successor_goal:
        raise RecoveryInheritanceError(
            "recovery requires the observed goal to match the expected goal "
            f"(expected {clean_string(goal)!r}, observed {successor_goal!r})"
        )
    baseline_inherited, baseline_diagnostics = _observe_baseline_inheritance(
        successor_artifacts_dir, predecessor_dir
    )
    (
        predecessor_repo_count,
        transferred_repo_count,
        inventory_missing,
        identity_diagnostics,
    ) = _observe_repo_transfer(predecessor_dir, successor_artifacts_dir)
    repo_diagnostics = _observe_repo_diagnostics(successor_artifacts_dir)
    return InheritanceEvidence(
        predecessor_goal=predecessor_goal,
        successor_goal=successor_goal,
        predecessor_bead=predecessor_bead,
        successor_bead=successor_bead,
        baseline_inherited=baseline_inherited,
        baseline_diagnostics=tuple(baseline_diagnostics),
        predecessor_repo_count=predecessor_repo_count,
        transferred_repo_count=transferred_repo_count,
        repo_diagnostics=(*identity_diagnostics, *repo_diagnostics),
        predecessor_autonomy=_live_predecessor_autonomy(record),
        predecessor_name=clean_string(record.get("agent_name")),
        explicit_autonomy_selection=explicit_autonomy_selection,
        parent_meta=dict(predecessor_meta),
        child_meta=dict(child_meta),
        successor_artifacts_dir=successor_artifacts_dir,
        predecessor_inventory_missing=inventory_missing,
    )


def _meta_goal(meta: Mapping[str, Any]) -> str | None:
    for key in ("goal_id", "goal"):
        value = clean_string(meta.get(key))
        if value:
            return value
    return None


def _observe_baseline_inheritance(
    successor_artifacts_dir: str | None,
    predecessor_artifacts_dir: str | None = None,
) -> tuple[bool, list[str]]:
    from sase.llm_provider.commit_finalizer_baseline import (
        BASELINE_FILENAME,
        FINALIZER_BASELINE_FILENAME,
        load_dirty_baseline,
    )
    from sase.llm_provider.commit_finalizer_inheritance import (
        INHERITANCE_DIAGNOSTICS_FILENAME,
    )

    diagnostics: list[str] = []
    if not successor_artifacts_dir:
        return False, ["successor artifacts directory is unknown"]
    root = Path(successor_artifacts_dir).expanduser()
    diagnostics_path = root / INHERITANCE_DIAGNOSTICS_FILENAME
    try:
        raw = diagnostics_path.read_text(encoding="utf-8")
    except OSError:
        raw = ""
    if raw.strip():
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if isinstance(payload, Mapping):
            entries = payload.get("diagnostics")
            if isinstance(entries, list):
                diagnostics.extend(str(item) for item in entries if str(item).strip())
        if not diagnostics:
            diagnostics.append(
                f"repository inheritance reported failure in "
                f"{INHERITANCE_DIAGNOSTICS_FILENAME}"
            )
    inherited = (root / BASELINE_FILENAME).is_file() or (
        root / FINALIZER_BASELINE_FILENAME
    ).is_file()
    if not inherited:
        diagnostics.append("successor baseline is not yet observable")
    if predecessor_artifacts_dir:
        try:
            parent_fingerprints = load_dirty_baseline(Path(predecessor_artifacts_dir))
        except Exception:
            parent_fingerprints = None
        if parent_fingerprints is None:
            diagnostics.append("predecessor baseline fingerprints are not observable")
        else:
            try:
                child_fingerprints = load_dirty_baseline(root)
            except Exception:
                child_fingerprints = None
            if child_fingerprints is None:
                diagnostics.append("successor baseline fingerprints are not observable")
            elif dict(child_fingerprints) != dict(parent_fingerprints):
                diagnostics.append(
                    "successor baseline fingerprints diverged from the "
                    "predecessor; a fresh snapshot of the predecessor's dirty "
                    "tree is never allowed"
                )
    return (inherited and not diagnostics, diagnostics)


def _observe_repo_transfer(
    predecessor_artifacts_dir: str | None,
    successor_artifacts_dir: str | None,
) -> tuple[int, int, bool, list[str]]:
    """Compare opened-repository obligations by identity, not just counts.

    Returns ``(predecessor_count, transferred_count, inventory_missing,
    diagnostics)``. ``inventory_missing`` is true when the predecessor's
    inventory could not be read at all -- a missing inventory must never
    pass as an empty one. Identity, workspace-directory, and direction
    mismatches land in *diagnostics* so validation fails closed.
    """
    from sase._linked_repo_markers import opened_repo_records

    missing = _predecessor_inventory_missing(predecessor_artifacts_dir)
    try:
        parent_records = (
            opened_repo_records(
                Path(predecessor_artifacts_dir).expanduser()
                if predecessor_artifacts_dir
                else None
            )
            if predecessor_artifacts_dir and not missing
            else {}
        )
    except Exception:
        parent_records = {}
        missing = True
    try:
        child_records = (
            opened_repo_records(Path(successor_artifacts_dir).expanduser())
            if successor_artifacts_dir
            else {}
        )
    except Exception:
        child_records = {}
    diagnostics: list[str] = []
    if not missing:
        for name in sorted(set(parent_records) - set(child_records)):
            diagnostics.append(f"missing opened-repository obligation: {name}")
        for name in sorted(set(child_records) - set(parent_records)):
            diagnostics.append(f"unexpected opened-repository obligation: {name}")
        for name in sorted(set(parent_records) & set(child_records)):
            parent_dir = parent_records[name].get("workspace_dir", "")
            child_dir = child_records[name].get("workspace_dir", "")
            if parent_dir != child_dir:
                diagnostics.append(
                    f"opened-repository workspace moved: {name} "
                    f"({parent_dir!r} != {child_dir!r})"
                )
    transferred = sum(
        1
        for name in parent_records
        if name in child_records
        and child_records[name].get("workspace_dir", "")
        == parent_records[name].get("workspace_dir", "")
    )
    return len(parent_records), transferred, missing, diagnostics


def _predecessor_inventory_missing(predecessor_artifacts_dir: str | None) -> bool:
    """Return whether the predecessor's inventory could not be read at all.

    An absent predecessor directory -- or a directory with neither
    opened-repository markers nor an ``agent_meta.json`` -- leaves no
    inventory to compare against, which must fail closed rather than pass
    vacuously as zero repositories.
    """
    if not predecessor_artifacts_dir:
        return True
    root = Path(predecessor_artifacts_dir).expanduser()
    try:
        if not root.is_dir():
            return True
    except OSError:
        return True
    from sase._linked_repo_markers import (
        OPENED_LINKED_FILENAME,
        OPENED_SIBLINGS_FILENAME,
    )

    markers = (root / OPENED_LINKED_FILENAME, root / OPENED_SIBLINGS_FILENAME)
    try:
        if any(path.is_file() for path in markers):
            return False
        return not (root / "agent_meta.json").is_file()
    except OSError:
        return True


def _observe_repo_diagnostics(successor_artifacts_dir: str | None) -> list[str]:
    from sase.llm_provider.commit_finalizer_inheritance import (
        INHERITANCE_DIAGNOSTICS_FILENAME,
    )

    if not successor_artifacts_dir:
        return ["successor artifacts directory is unknown"]
    try:
        raw = (
            Path(successor_artifacts_dir).expanduser()
            / INHERITANCE_DIAGNOSTICS_FILENAME
        ).read_text(encoding="utf-8")
    except OSError:
        return []
    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except ValueError:
        return [f"could not parse {INHERITANCE_DIAGNOSTICS_FILENAME}"]
    if isinstance(payload, Mapping):
        entries = payload.get("diagnostics")
        if isinstance(entries, list):
            return [str(item) for item in entries if str(item).strip()]
    return []


def _live_predecessor_autonomy(
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    from sase.autonomy.record import live_record

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return None
    try:
        found = live_record(artifacts_dir)
    except Exception:
        return None
    return dict(found) if isinstance(found, Mapping) else None


def settle_recovery(
    record: Mapping[str, Any],
    *,
    action: str,
    successor_name: str,
    successor_pid: int | None = None,
    successor_process_identity_token: str | None = None,
    successor_artifacts_dir: str | None = None,
    inheritance_acknowledged: bool = True,
    launch_identity: str | None = None,
    admission_request_id: str | None = None,
    admission_identity: str | None = None,
    advance_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
    | None = None,
    write_done_fn: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Idempotently settle a resolving record and its predecessor marker.

    CASes ``resolving`` to ``resolved`` with the confirmed successor
    evidence, then writes the predecessor ``done.json`` recovery fields
    (``state``, ``action``, ``successor``, ``model_changed``) while
    preserving ``outcome: hijacked``. A record already ``resolved`` with
    the same successor skips the CAS and repairs ``done.json`` only, so
    the reconcile phase can rerun this helper after an interrupted write.
    A non-hijack ``done.json`` outcome refuses: the predecessor finished
    first and its marker must not be rewritten.
    """
    current = dict(record)
    state = clean_string(current.get("state")) or ""
    hijack_id = clean_string(current.get("hijack_id")) or ""
    if state == "resolved":
        existing = clean_string(current.get("reserved_successor_name")) or (
            clean_string((current.get("recovery") or {}).get("successor"))
            if isinstance(current.get("recovery"), Mapping)
            else ""
        )
        done_recovery: Mapping[str, Any] | None = None
        artifacts = clean_string(current.get("artifacts_dir"))
        if artifacts:
            _, done_recovery = read_predecessor_done_marker(current)
        done_successor = (
            clean_string(done_recovery.get("successor"))
            if isinstance(done_recovery, Mapping)
            else None
        )
        if (existing and existing == successor_name) or (
            done_successor and done_successor == successor_name
        ):
            (write_done_fn or _write_predecessor_settlement)(
                current,
                action=action,
                successor_name=successor_name,
                launch_identity=launch_identity,
            )
            return _fresh_record(current, hijack_id)
        raise ledger.HijackLedgerConflict(
            f"hijack record {hijack_id} already resolved for "
            f"{existing or done_successor or 'another successor'}"
        )
    if state != "resolving":
        raise RecoveryRefusal(
            "not_resolving",
            f"Recovery settlement requires a resolving record (state {state!r})",
        )
    _check_predecessor_outcome(current)
    advance = advance_fn or _cas_advance
    event: dict[str, Any] = {
        "event": "complete_resolution",
        "launch_stage": "confirmed",
        "successor_artifacts_dir": successor_artifacts_dir,
        "inheritance_acknowledged": bool(inheritance_acknowledged),
    }
    if successor_pid is not None:
        event["successor_pid"] = int(successor_pid)
    if successor_process_identity_token:
        event["successor_process_identity_token"] = successor_process_identity_token
    if launch_identity:
        event["launch_identity"] = launch_identity
    if admission_request_id:
        event["admission_request_id"] = admission_request_id
    if admission_identity:
        event["admission_identity"] = admission_identity
    updated = dict(advance(current, event))
    (write_done_fn or _write_predecessor_settlement)(
        updated,
        action=action,
        successor_name=successor_name,
        launch_identity=launch_identity,
    )
    return updated


def _cas_advance(
    record: Mapping[str, Any], event: Mapping[str, Any]
) -> Mapping[str, Any]:
    return ledger.cas_advance_record(dict(record), dict(event))


def _check_predecessor_outcome(record: Mapping[str, Any]) -> None:
    """Refuse settlement when the predecessor outcome is not hijacked.

    Runs before the ``complete_resolution`` CAS so a finished-first
    predecessor never gains a resolved recovery. A missing ``done.json``
    is allowed: the settlement write repairs it with a minimal marker.
    """
    from sase.history.chat_fork.common import load_json_object

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return
    payload = load_json_object(Path(artifacts_dir) / "done.json")
    if not isinstance(payload, Mapping) or not payload:
        return
    outcome = payload.get("outcome")
    if (
        isinstance(outcome, str)
        and outcome.strip()
        and outcome.strip().lower() != "hijacked"
    ):
        raise RecoveryRefusal(
            "outcome_changed",
            f"The predecessor outcome is {outcome!r}, not hijacked; "
            "its marker must not be rewritten",
        )


def _fresh_record(record: Mapping[str, Any], hijack_id: str) -> dict[str, Any]:
    reloaded = ledger.load_record(hijack_id)
    if isinstance(reloaded, Mapping) and reloaded:
        return dict(reloaded)
    return dict(record)


def _write_predecessor_settlement(
    record: Mapping[str, Any],
    *,
    action: str,
    successor_name: str,
    launch_identity: str | None = None,
) -> None:
    """Write the predecessor ``done.json`` recovery fields, preserving outcome.

    ``outcome: hijacked`` stays untouched; only the ``recovery`` object
    gains the resolved keep-work fields. Missing ``done.json`` gains a
    minimal hijacked marker so status readers still resolve
    ``ESCALATED``/``CONTINUED`` through the existing Rust mapping. A real
    non-hijack outcome refuses loudly instead of rewriting history.
    """
    from sase.notification_gates.durability import atomic_write_json
    from sase.core.agent_artifact_index_lifecycle import (
        update_agent_artifact_index_for_marker_mutation,
    )

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        raise RecoveryRefusal(
            "missing_artifacts",
            "The hijack record has no predecessor artifact directory",
        )
    path = Path(artifacts_dir) / "done.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = None
    except (OSError, ValueError) as exc:
        raise RecoveryRefusal(
            "unreadable_done_marker",
            f"Could not read the predecessor done.json: {exc}",
        ) from exc
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RecoveryRefusal(
            "unreadable_done_marker",
            "The predecessor done.json is not a JSON object",
        )
    outcome = payload.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        if outcome.strip().lower() != "hijacked":
            raise RecoveryRefusal(
                "outcome_changed",
                f"The predecessor outcome is {outcome!r}, not hijacked; "
                "its marker must not be rewritten",
            )
    else:
        payload["outcome"] = "hijacked"
    if launch_identity is None:
        launch_identity = clean_string(record.get("launch_identity"))
    model_changed = record.get("model_changed")
    recovery = payload.get("recovery")
    merged = dict(recovery) if isinstance(recovery, Mapping) else {}
    merged.update(
        {
            "state": "resolved",
            "kind": "hijack",
            "hijack_id": clean_string(record.get("hijack_id")),
            "action": action,
            "successor": successor_name,
            "model_changed": bool(model_changed),
        }
    )
    if launch_identity:
        merged.setdefault("launch_identity", launch_identity)
    payload["recovery"] = merged
    try:
        atomic_write_json(path, payload)
    except OSError as exc:
        raise RecoveryRefusal(
            "unwritable_done_marker",
            f"Could not write the predecessor done.json: {exc}",
        ) from exc
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
