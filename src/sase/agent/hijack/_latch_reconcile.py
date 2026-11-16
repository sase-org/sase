"""Identity-checked recovery of pending and partially applied hijack latches."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import core, ledger, latch
from sase.agent.hijack._latch_reconcile_evidence import (
    clear_error,
    matching_claim,
    owner_observation,
    read_real_outcome,
    save_error,
    successor_observation,
    suppressed_stage,
    target_from_record,
)

_RECONCILE_BOUNDARY = "owner_recovery"


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def reconcile_latched_records(
    *,
    log_fn: Callable[[str, str | None], None] | None = None,
) -> None:
    """Reconcile dead latch owners without depending on live agent-row scans."""
    try:
        records = ledger.list_active_records()
    except Exception:
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("state") or "") not in {"latched", "stopping"}:
            continue
        _reconcile_record(record, log_fn=log_fn)


def _reconcile_record(
    record: dict[str, Any],
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> None:
    artifacts_dir = _string(record.get("artifacts_dir"))
    hijack_id = _string(record.get("hijack_id"))
    target_key = _string(record.get("target_key"))
    if not artifacts_dir or not hijack_id or not target_key:
        _log(
            log_fn,
            "Hijack latch lacks identity data; recovery retained custody",
            "yellow",
        )
        return

    # Adoption is the outer lock for staged handoffs. A busy runner owns the
    # decision for now; the next sweep re-reads the receipt and manifest.
    try:
        from sase.agent.staged_handoff import acquire_adoption_lock

        with acquire_adoption_lock(Path(artifacts_dir), blocking=False) as acquired:
            if not acquired:
                return
            _reconcile_under_adoption_lock(
                hijack_id,
                target_key,
                artifacts_dir,
                log_fn=log_fn,
            )
    except Exception as exc:  # noqa: BLE001 - stale sweeping always fails closed.
        save_error(
            hijack_id, f"latch reconciliation could not inspect handoff evidence: {exc}"
        )
        _log(
            log_fn,
            f"Hijack {hijack_id} retains workspace (handoff evidence uncertain)",
            "yellow",
        )


def _reconcile_under_adoption_lock(
    hijack_id: str,
    target_key: str,
    artifacts_dir: str,
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> None:
    current = ledger.load_record(hijack_id)
    if current is None or str(current.get("target_key") or "") != target_key:
        return
    state = str(current.get("state") or "")
    if state not in {"latched", "stopping"}:
        return
    project_file = _string(current.get("project_file"))
    owner, owner_state = owner_observation(current)
    if owner_state != "dead":
        # A matching live owner is left pending. Unknown identity/liveness is
        # also fail-closed; neither condition authorizes recovery effects.
        if owner_state == "unknown":
            save_error(
                hijack_id,
                "owner liveness or process identity is uncertain; retain latch custody",
            )
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace (owner liveness uncertain)",
                "yellow",
            )
        return

    successor, successor_error = successor_observation(current, artifacts_dir)
    outcome = read_real_outcome(artifacts_dir)
    if state == "latched":
        if successor_error:
            save_error(hijack_id, successor_error)
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace (successor evidence uncertain)",
                "yellow",
            )
            return
        facts = {
            "schema_version": core.agent_hijack_latch_wire_schema_version(),
            "owner": owner,
            "successor": successor,
            "boundary_outcome": outcome,
        }
        try:
            decision = core.hijack_latch_reconcile(current, facts)
        except Exception as exc:  # noqa: BLE001 - keep custody if Rust rejects evidence.
            save_error(hijack_id, f"latch reconciliation policy failed: {exc}")
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace (reconcile policy unavailable)",
                "yellow",
            )
            return
        action = str(decision.get("outcome") or "")
        if action == "keep_pending":
            clear_error(hijack_id)
            return
        if action == "moot_latch":
            # A valid successor can already have transferred the numbered
            # claim. Mooting only releases the old target reservation; it does
            # not touch the successor's claim or artifacts.
            target = target_from_record(current, None, outcome)
            result = latch.moot_latch(
                target_key,
                _RECONCILE_BOUNDARY,
                outcome or "completed",
                target=target,
            )
            if result.get("verdict") == "moot":
                clear_error(hijack_id)
                _log(
                    log_fn,
                    f"Hijack {hijack_id} finished first; adopted successor was preserved",
                    "cyan",
                )
            return
        if action != "apply_latch":
            message = str(
                decision.get("message") or "owner or successor evidence is uncertain"
            )
            save_error(hijack_id, message)
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace ({decision.get('code') or 'uncertain'}: {message})",
                "yellow",
            )
            return
        suppressed, suppressed_error = suppressed_stage(artifacts_dir)
        if suppressed_error:
            save_error(hijack_id, suppressed_error)
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace (staged payload uncertain)",
                "yellow",
            )
            return
        claim = matching_claim(current, project_file, artifacts_dir)
        if claim is None:
            save_error(
                hijack_id,
                "the exact numbered workspace claim is unavailable; latch recovery retained custody",
            )
            _log(
                log_fn,
                f"Hijack {hijack_id} retains workspace (claim identity unavailable)",
                "yellow",
            )
            return
        target = target_from_record(current, claim, outcome)
        result = latch.apply_reconciled_latch(
            target_key,
            target=target,
            boundary_outcome=outcome or "interrupted",
            suppressed_followup=suppressed,
        )
        _log_repair_result(hijack_id, result, log_fn)
        return

    # A stopping record means the latch already won its boundary/force CAS.
    # Never turn an adopted successor into another suppressed handoff.
    if successor_error or successor.get("kind") != "absent":
        message = (
            successor_error
            or "a successor may already own the staged handoff; stopping repair was withheld"
        )
        save_error(hijack_id, message)
        _log(
            log_fn,
            f"Hijack {hijack_id} retains workspace (successor may already be adopted)",
            "yellow",
        )
        return
    claim = matching_claim(current, project_file, artifacts_dir)
    if claim is None:
        save_error(
            hijack_id,
            "the exact numbered workspace claim is unavailable; latch recovery retained custody",
        )
        _log(
            log_fn,
            f"Hijack {hijack_id} retains workspace (claim identity unavailable)",
            "yellow",
        )
        return
    target = target_from_record(current, claim, outcome)
    result = latch.apply_reconciled_latch(
        target_key,
        target=target,
        boundary_outcome=_string(current.get("boundary_outcome"))
        or outcome
        or "interrupted",
    )
    _log_repair_result(hijack_id, result, log_fn)


def _log_repair_result(
    hijack_id: str,
    result: Mapping[str, Any],
    log_fn: Callable[[str, str | None], None] | None,
) -> None:
    verdict = str(result.get("verdict") or "")
    if verdict == "applied" and result.get("ready") is not False:
        _log(
            log_fn,
            f"Hijack {hijack_id} reconciled its dead owner and retained the workspace",
            "cyan",
        )
    elif result.get("message"):
        _log(
            log_fn,
            f"Hijack {hijack_id} retains workspace ({result.get('code')}: {result.get('message')})",
            "yellow",
        )


def _log(
    log_fn: Callable[[str, str | None], None] | None,
    message: str,
    style: str | None,
) -> None:
    if log_fn is not None:
        try:
            log_fn(message, style)
        except Exception:
            pass


__all__ = ["reconcile_latched_records"]
