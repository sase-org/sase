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

import logging
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.core import hijack_recovery_reconcile
from sase.agent.hijack.recover_common import (
    RecoveryDeps,
    clean_string,
    fail_to_held,
    record_pid,
    reload_record,
)
from sase.agent.hijack.recover_settle import settle_recovery
from sase.agent.hijack._recover_reconcile_observation import (
    RECONCILE_MIN_AGE_SECONDS,
    ReconcileDeps,
    gather_reconcile_facts,
    successor_artifacts_dir,
)
from sase.agent.hijack._recover_reconcile_pending import (
    add_pending_repair,
    clear_pending_repair,
    read_pending_repairs,
)

LOG = logging.getLogger(__name__)


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
    clear_pending_repair(clean_string(record.get("hijack_id")) or "")
    return True


def repair_pending_settlements(limit: int = 20) -> int:
    """Repair at most *limit* pending settled projections by id lookup."""
    pending = read_pending_repairs()[: max(0, limit)]
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
                    clear_pending_repair(hijack_id)
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
    add_pending_repair(hijack_id)
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
            successor_artifacts_dir=successor_artifacts_dir(record, deps=deps),
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
    clear_pending_repair(hijack_id)
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


__all__ = [
    "RECONCILE_MIN_AGE_SECONDS",
    "ReconcileDeps",
    "gather_reconcile_facts",
    "reconcile_recovery",
    "repair_pending_settlements",
    "repair_settled_projection",
]
