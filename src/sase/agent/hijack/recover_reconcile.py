"""Crash repair for interrupted keep-work recovery.

Phase ``reconcile_wait``: reconcile abandoned ``resolving`` records from
durable launch evidence, repair partially written settlement, and expose
one idempotent entry point for mutating recovery calls and stale cleanup.

Rust owns the reconcile decision (:func:`hijack_recovery_reconcile`);
this module owns Python observation. Names alone never prove a successor:
launch identity, admission identity, workspace, lineage, and inheritance
acknowledgement must match the reservation before adoption.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.core import (
    hijack_recovery_reconcile,
    hijack_recovery_reconcile_wire_schema_version,
)
from sase.agent.hijack.recover_common import (
    RecoveryDeps,
    clean_string,
    fail_to_held,
    record_pid,
    record_revision,
    record_workspace_num,
    reload_record,
)
from sase.agent.hijack.recover_settle import settle_recovery

LOG = logging.getLogger(__name__)

#: A resolving record younger than this is never repaired. Matches the
#: Rust default ``min_age_seconds`` in ``reconcile.rs``.
RECONCILE_MIN_AGE_SECONDS = 60.0

#: Bounded pending-repair tracking: hijack ids whose ``resolved`` CAS may
#: have landed before ``done.json`` was repaired. Never scan ``settled/``.
_PENDING_REPAIRS_FILENAME = "pending_recovery_repairs.json"
_PENDING_REPAIRS_LIMIT = 50


@dataclass
class ReconcileDeps:
    """Injectable seams for reconciliation observation."""

    is_process_running: Callable[[int], bool] | None = None
    process_identity_token: Callable[[int], str | None] | None = None
    observe_admission: Callable[[str], Mapping[str, Any]] | None = None
    load_successor_artifacts: Callable[[Mapping[str, Any]], str | None] | None = None
    now_unix: Callable[[], float] | None = None


def reconcile_recovery(
    hijack_id_or_record: str | Mapping[str, Any],
    *,
    deps: ReconcileDeps | RecoveryDeps | None = None,
) -> dict[str, Any]:
    """Reconcile one ``resolving`` record from durable launch evidence.

    Returns the Rust decision plus the repair action taken
    (``none``, ``adopted``, ``returned_to_held``, ``pending_repair``).
    Retaining custody (``keep_resolving`` / ``retain_with_error``) performs
    no ledger mutation so two cleanup processes cannot duplicate a launch.
    """
    record = _load_target(hijack_id_or_record)
    if record is None:
        return {
            "outcome": "retain_with_error",
            "code": "record_not_found",
            "message": "No hijack record was found",
            "action_taken": "none",
        }
    if clean_string(record.get("state")) != "resolving":
        if clean_string(record.get("state")) == "resolved":
            repaired = repair_settled_projection(record)
            return {
                "outcome": "adopt",
                "code": "already_resolved",
                "message": "Record is already resolved",
                "action_taken": "pending_repair" if repaired else "none",
                "record": record,
            }
        return {
            "outcome": "retain_with_error",
            "code": "not_resolving",
            "message": "Reconciliation only applies to resolving records",
            "action_taken": "none",
            "record": record,
        }
    facts = gather_reconcile_facts(record, deps=deps)
    try:
        decision = hijack_recovery_reconcile(dict(record), dict(facts))
    except Exception as exc:
        LOG.warning("reconcile decision failed: %s", exc)
        return {
            "outcome": "retain_with_error",
            "code": "decision_failed",
            "message": str(exc),
            "action_taken": "none",
            "record": record,
        }
    outcome = str(decision.get("outcome") or "")
    if outcome == "adopt":
        return _adopt_proven_successor(record, decision, deps=deps)
    if outcome == "return_to_held":
        return _return_to_held(record, decision)
    return {
        "outcome": outcome,
        "code": decision.get("code"),
        "message": decision.get("message"),
        "action_taken": "none",
        "record": reload_record(str(record.get("hijack_id") or ""), record),
    }


def gather_reconcile_facts(
    record: Mapping[str, Any],
    *,
    deps: ReconcileDeps | RecoveryDeps | None = None,
) -> dict[str, Any]:
    """Build the ``AgentHijackReconcileFactsWire`` for *record*."""
    seams = _as_reconcile_seams(deps)
    now = seams.now_unix() if seams.now_unix is not None else time.time()
    age = _resolving_age_seconds(record, now_unix=now)
    resolver = _observe_resolver(record, seams=seams)
    successor = _observe_successor(record, seams=seams)
    return {
        "schema_version": hijack_recovery_reconcile_wire_schema_version(),
        "now_unix": float(now),
        "resolving_age_seconds": float(age),
        "min_age_seconds": float(RECONCILE_MIN_AGE_SECONDS),
        "resolver": resolver,
        "successor": successor,
    }


def repair_settled_projection(record_or_id: str | Mapping[str, Any]) -> bool:
    """Repair ``done.json`` when the ledger already resolved.

    Uses authoritative single-id lookup (active then ``settled/``), never
    a ``settled/`` directory scan. Returns True when a repair write ran.
    """
    record = _load_target(record_or_id)
    if record is None or clean_string(record.get("state")) != "resolved":
        return False
    successor = clean_string(record.get("reserved_successor_name"))
    if not successor:
        recovery = record.get("recovery")
        if isinstance(recovery, Mapping):
            successor = clean_string(recovery.get("successor"))
    if not successor:
        return False
    action = clean_string(record.get("resolution_action")) or "continue"
    try:
        settle_recovery(
            dict(record),
            action=action,
            successor_name=successor,
            successor_pid=record_pid(record.get("successor_pid")),
            successor_process_identity_token=clean_string(
                record.get("successor_process_identity_token")
            ),
            successor_artifacts_dir=clean_string(record.get("successor_artifacts_dir")),
            inheritance_acknowledged=bool(record.get("inheritance_acknowledged", True)),
            launch_identity=clean_string(record.get("launch_identity")),
            admission_request_id=clean_string(record.get("admission_request_id")),
            admission_identity=clean_string(record.get("admission_identity")),
        )
    except Exception as exc:
        LOG.warning("settled projection repair failed: %s", exc)
        return False
    _clear_pending_repair(clean_string(record.get("hijack_id")) or "")
    return True


def repair_pending_settlements(limit: int = 20) -> int:
    """Repair at most *limit* pending settled projections by id lookup."""
    pending = _read_pending_repairs()[: max(0, limit)]
    repaired = 0
    for hijack_id in pending:
        try:
            if repair_settled_projection(hijack_id):
                repaired += 1
            else:
                current = ledger.load_record(hijack_id)
                if current is None or clean_string(current.get("state")) not in {
                    "resolving",
                    "resolved",
                }:
                    _clear_pending_repair(hijack_id)
        except Exception:
            continue
    return repaired


def _adopt_proven_successor(
    record: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    deps: ReconcileDeps | RecoveryDeps | None = None,
) -> dict[str, Any]:
    hijack_id = clean_string(record.get("hijack_id")) or ""
    successor = clean_string(decision.get("successor_name")) or clean_string(
        record.get("reserved_successor_name")
    )
    if not successor:
        return {
            "outcome": str(decision.get("outcome") or ""),
            "code": "missing_successor",
            "message": "Adopt decision carries no successor name",
            "action_taken": "none",
            "record": dict(record),
        }
    _add_pending_repair(hijack_id)
    action = clean_string(record.get("resolution_action")) or "continue"
    try:
        settled = settle_recovery(
            dict(record),
            action=action,
            successor_name=successor,
            successor_pid=record_pid(record.get("successor_pid")),
            successor_process_identity_token=clean_string(
                record.get("successor_process_identity_token")
            ),
            successor_artifacts_dir=_successor_artifacts_dir(record, deps=deps),
            inheritance_acknowledged=True,
            launch_identity=clean_string(record.get("launch_identity"))
            or clean_string(decision.get("launch_identity")),
            admission_request_id=clean_string(record.get("admission_request_id")),
            admission_identity=clean_string(record.get("admission_identity")),
        )
    except Exception as exc:
        LOG.warning("reconcile adopt failed for %s: %s", hijack_id, exc)
        return {
            "outcome": str(decision.get("outcome") or ""),
            "code": decision.get("code"),
            "message": f"Adopted successor could not settle: {exc}",
            "action_taken": "pending_repair",
            "record": reload_record(hijack_id, record),
        }
    _clear_pending_repair(hijack_id)
    return {
        "outcome": str(decision.get("outcome") or ""),
        "code": decision.get("code"),
        "message": decision.get("message"),
        "action_taken": "adopted",
        "record": settled,
    }


def _return_to_held(
    record: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    hijack_id = clean_string(record.get("hijack_id")) or ""
    message = clean_string(decision.get("message")) or "No successor owns the work"
    fail_to_held(dict(record), message)
    return {
        "outcome": str(decision.get("outcome") or ""),
        "code": decision.get("code"),
        "message": decision.get("message"),
        "action_taken": "returned_to_held",
        "record": reload_record(hijack_id, record),
    }


def _load_target(
    hijack_id_or_record: str | Mapping[str, Any],
) -> dict[str, Any] | None:
    if isinstance(hijack_id_or_record, Mapping):
        candidate = dict(hijack_id_or_record)
        if clean_string(candidate.get("hijack_id")):
            fresh = ledger.load_record(str(candidate["hijack_id"]))
            if isinstance(fresh, Mapping) and fresh:
                return dict(fresh)
            return candidate
        return candidate
    current = ledger.load_record(hijack_id_or_record)
    return dict(current) if isinstance(current, Mapping) else None


def _as_reconcile_seams(
    deps: ReconcileDeps | RecoveryDeps | None,
) -> ReconcileDeps:
    if deps is None or isinstance(deps, ReconcileDeps):
        return deps or ReconcileDeps()
    token_fn = getattr(deps, "process_identity_token", None)
    observe = getattr(deps, "observe_admission", None)
    return ReconcileDeps(
        process_identity_token=token_fn,
        observe_admission=observe,
    )


def _resolving_age_seconds(record: Mapping[str, Any], *, now_unix: float) -> float:
    from sase.core.time import parse_local

    for key in ("updated_at", "hijacked_at"):
        raw = clean_string(record.get(key))
        if not raw:
            continue
        try:
            parsed = parse_local(raw)
        except Exception:
            continue
        if parsed is None:
            continue
        try:
            return max(0.0, float(now_unix) - parsed.timestamp())
        except Exception:
            continue
    return 0.0


def _observe_resolver(
    record: Mapping[str, Any], *, seams: ReconcileDeps
) -> dict[str, Any]:
    pid = record_pid(record.get("resolver_pid"))
    recorded_token = clean_string(record.get("resolver_process_identity_token"))
    if pid is None:
        return {
            "pid_live": False,
            "identity_matches": False,
            "observed_pid": None,
            "observed_identity_token": None,
        }
    pid_live = _pid_live(pid, seams=seams)
    observed_token: str | None = None
    if seams.process_identity_token is not None:
        try:
            observed_token = seams.process_identity_token(pid)
        except Exception:
            observed_token = None
    else:
        observed_token = _process_identity_token(pid)
    if not observed_token:
        observed_token = None
    identity_matches = bool(
        pid_live and recorded_token and observed_token == recorded_token
    )
    return {
        "pid_live": bool(pid_live),
        "identity_matches": bool(identity_matches),
        "observed_pid": int(pid),
        "observed_identity_token": observed_token,
    }


def _observe_successor(
    record: Mapping[str, Any], *, seams: ReconcileDeps
) -> dict[str, Any]:
    recorded_launch = clean_string(record.get("launch_identity"))
    recorded_request = clean_string(record.get("admission_request_id"))
    recorded_identity = clean_string(record.get("admission_identity"))
    reserved_name = clean_string(record.get("reserved_successor_name"))
    expected_workspace = record_workspace_num(record)
    expected_dir = clean_string(record.get("workspace_dir"))
    artifacts_dir = _successor_artifacts_dir(record, deps=seams)
    admission = _observe_admission(recorded_request, seams=seams)
    ack = _read_ack(artifacts_dir)
    meta = _read_meta(artifacts_dir)
    observed_launch = clean_string((ack or {}).get("launch_identity"))
    if observed_launch is None and ack is None:
        observed_launch = None
    observed_request = clean_string(admission.get("request_id")) if admission else None
    observed_identity = (
        clean_string(admission.get("dispatch_fingerprint"))
        or clean_string(admission.get("identity"))
        if admission
        else None
    )
    if observed_request is None:
        observed_request = (
            clean_string(admission.get("request_id")) if admission else None
        )
    observed_pid = record_pid((meta or {}).get("pid"))
    observed_token = clean_string((meta or {}).get("process_identity"))
    observed_name = clean_string((meta or {}).get("name")) or clean_string(
        (ack or {}).get("successor_name")
    )
    observed_dir = clean_string((meta or {}).get("artifacts_dir")) or artifacts_dir
    workspace_num = _meta_workspace_num(meta, ack)
    workspace_dir = clean_string((ack or {}).get("workspace_dir"))
    lineage = _lineage_payload((ack or {}).get("lineage"))
    expected_lineage = _expected_lineage(record)
    launch_matches = bool(
        recorded_launch and observed_launch and observed_launch == recorded_launch
    )
    workspace_matches = bool(
        expected_workspace is not None
        and workspace_num == expected_workspace
        and expected_dir
        and workspace_dir
        and _same_path(workspace_dir, expected_dir)
    )
    lineage_matches = bool(expected_lineage and lineage == expected_lineage)
    inheritance_ack = bool(record.get("inheritance_acknowledged", False)) or bool(
        (ack or {}).get("baseline_inherited")
    )
    kind = _successor_kind(
        record=record,
        admission=admission,
        ack=ack,
        meta=meta,
        artifacts_dir=artifacts_dir,
        recorded_launch=recorded_launch,
        recorded_request=recorded_request,
    )
    # ``name_only`` means the observer found a bare name without launch or
    # process identity. An absent observation is not a bare name: it means
    # nothing was observed, so the Rust decision can return to held when no
    # launch evidence was ever recorded.
    name_only = bool(
        kind not in {"absent", "queued"}
        and (observed_name or reserved_name)
        and not observed_launch
        and observed_pid is None
        and not observed_token
        and not launch_matches
    )
    return {
        "kind": kind,
        "launch_identity": observed_launch,
        "admission_request_id": observed_request or recorded_request,
        "admission_identity": observed_identity or recorded_identity,
        "name": observed_name or reserved_name,
        "pid": observed_pid,
        "process_identity_token": observed_token,
        "artifacts_dir": observed_dir,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "launch_identity_matches": launch_matches,
        "workspace_matches": workspace_matches,
        "lineage_matches": lineage_matches,
        "inheritance_acknowledged": inheritance_ack,
        "name_only": name_only,
    }


def _successor_kind(
    *,
    record: Mapping[str, Any],
    admission: Mapping[str, Any] | None,
    ack: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
    artifacts_dir: str | None,
    recorded_launch: str | None,
    recorded_request: str | None,
) -> str:
    if admission is not None:
        state = clean_string(admission.get("state")) or ""
        admission_request = clean_string(admission.get("request_id"))
        if state == "mismatch" or (
            recorded_request
            and admission_request
            and admission_request != recorded_request
        ):
            return "mismatched"
        if state in {"submitted", "reserved", "waiting", "checking", "eligible"}:
            return "queued"
        if state in {"missing", "mismatch"} and not recorded_launch:
            return "absent"
        if state == "uncertain":
            return "uncertain"
    if ack is None and meta is None and artifacts_dir is None:
        if recorded_launch or recorded_request:
            return "uncertain"
        return "absent"
    if _successor_completed(artifacts_dir):
        return "completed"
    return "live"


def _successor_completed(artifacts_dir: str | None) -> bool:
    if not artifacts_dir:
        return False
    try:
        payload = json.loads(
            (Path(artifacts_dir) / "done.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    outcome = payload.get("outcome")
    return isinstance(outcome, str) and outcome.strip() != ""


def _observe_admission(
    request_id: str | None, *, seams: ReconcileDeps
) -> Mapping[str, Any] | None:
    if not request_id:
        return None
    observe = seams.observe_admission
    if observe is None:
        try:
            from sase.agent.hijack.recovery_admission import (
                observe_recovery_admission,
            )
        except Exception:
            return None
        observe = observe_recovery_admission
    try:
        result = observe(request_id)
    except Exception:
        return None
    return dict(result) if isinstance(result, Mapping) else None


def _successor_artifacts_dir(
    record: Mapping[str, Any],
    *,
    deps: ReconcileDeps | RecoveryDeps | None = None,
) -> str | None:
    direct = clean_string(record.get("successor_artifacts_dir"))
    if direct:
        return direct
    seams = _as_reconcile_seams(deps)
    if seams.load_successor_artifacts is not None:
        try:
            value = seams.load_successor_artifacts(record)
        except Exception:
            value = None
        if clean_string(value):
            return clean_string(value)
    reserved = clean_string(record.get("reserved_successor_name"))
    if not reserved:
        return None
    try:
        from sase.agent.names import find_named_agent
    except Exception:
        return None
    try:
        found = find_named_agent(reserved)
    except Exception:
        return None
    artifacts = clean_string(getattr(found, "artifacts_dir", None))
    return artifacts


def _read_ack(artifacts_dir: str | None) -> dict[str, Any] | None:
    if not artifacts_dir:
        return None
    try:
        from sase.agent.hijack.recovery_successor import read_recovery_ack
    except Exception:
        return None
    try:
        ack = read_recovery_ack(artifacts_dir)
    except Exception:
        return None
    return dict(ack) if isinstance(ack, Mapping) else None


def _read_meta(artifacts_dir: str | None) -> dict[str, Any] | None:
    if not artifacts_dir:
        return None
    try:
        from sase.history.chat_fork.common import load_json_object
    except Exception:
        try:
            from history.chat_fork.common import load_json_object  # type: ignore
        except Exception:
            return None
    try:
        value = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    except Exception:
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _meta_workspace_num(
    meta: Mapping[str, Any] | None, ack: Mapping[str, Any] | None
) -> int | None:
    for source in (ack, meta):
        if not isinstance(source, Mapping):
            continue
        for key in ("workspace_num", "workspaceNum"):
            try:
                value = int(source.get(key))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


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


def _expected_lineage(record: Mapping[str, Any]) -> dict[str, Any]:
    lineage: dict[str, Any] = {
        "hijack_id": clean_string(record.get("hijack_id")) or "",
        "predecessor": clean_string(record.get("agent_name")) or "",
    }
    return {key: value for key, value in lineage.items() if value}


def _pid_live(pid: int, *, seams: ReconcileDeps) -> bool:
    if seams.is_process_running is not None:
        try:
            return bool(seams.is_process_running(int(pid)))
        except Exception:
            return False
    try:
        from sase.ace.hooks.processes import is_process_running
    except Exception:
        return False
    try:
        return bool(is_process_running(int(pid)))
    except Exception:
        return False


def _process_identity_token(pid: int) -> str | None:
    try:
        from sase.core.process_identity import process_identity_token
    except Exception:
        return None
    try:
        token = process_identity_token(int(pid))
    except Exception:
        return None
    return token or None


def _same_path(left: str | None, right: str | None) -> bool:
    import os

    if not left or not right:
        return False
    try:
        return os.path.normcase(os.path.normpath(left)) == os.path.normcase(
            os.path.normpath(right)
        )
    except Exception:
        return False


def _pending_repairs_path() -> Path:
    from sase.core.paths import sase_subdir
    from sase.agent.hijack.ledger import LEDGER_DIRNAME

    return sase_subdir(LEDGER_DIRNAME) / _PENDING_REPAIRS_FILENAME


def _read_pending_repairs() -> list[str]:
    try:
        payload = json.loads(_pending_repairs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    seen: list[str] = []
    for entry in payload:
        if isinstance(entry, str) and entry and entry not in seen:
            seen.append(entry)
    return seen[:_PENDING_REPAIRS_LIMIT]


def _add_pending_repair(hijack_id: str) -> None:
    if not hijack_id:
        return
    pending = _read_pending_repairs()
    if hijack_id not in pending:
        pending.append(hijack_id)
    try:
        _pending_repairs_path().parent.mkdir(parents=True, exist_ok=True)
        _pending_repairs_path().write_text(
            json.dumps(pending[-_PENDING_REPAIRS_LIMIT:]), encoding="utf-8"
        )
    except OSError:
        LOG.warning("could not track pending recovery repair", exc_info=True)


def _clear_pending_repair(hijack_id: str) -> None:
    if not hijack_id:
        return
    pending = [entry for entry in _read_pending_repairs() if entry != hijack_id]
    try:
        _pending_repairs_path().write_text(json.dumps(pending), encoding="utf-8")
    except OSError:
        pass


__all__ = [
    "RECONCILE_MIN_AGE_SECONDS",
    "ReconcileDeps",
    "gather_reconcile_facts",
    "reconcile_recovery",
    "repair_pending_settlements",
    "repair_settled_projection",
]
