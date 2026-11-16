"""Hijack-custody helpers for the stale RUNNING entry sweep."""

from collections.abc import Callable
from datetime import UTC
from typing import Any

from sase.running_field import WorkspaceClaim

from ..hooks.processes import is_process_running
from ._stale_running_shared import (
    clear_stale_occupant_record,
    held_claim_ttl_days,
    settle_stale_retention_record,
)

HIJACK_LOOKUP_FAILED = object()


def matching_hijack_record(
    project_file: str, claim: WorkspaceClaim
) -> dict[str, Any] | object | None:
    """Return the active hijack record, or a sentinel when lookup itself failed.

    Lookup failures fail closed: the claim stays until a later sweep can
    prove it is not hijacked.
    """
    try:
        from sase.agent.hijack.custody import matching_active_record

        return matching_active_record(project_file, claim)
    except Exception:
        return HIJACK_LOOKUP_FAILED


def apply_hijack_custody(
    project_file: str,
    claim: WorkspaceClaim,
    record: dict[str, Any],
    *,
    held_ttl_days: int | None,
    log_fn: Callable[[str, str | None], None] | None = None,
) -> tuple[bool, int | None]:
    """Retain or expire one hijack-owned claim. Never fall through to generic release."""
    from sase.agent.hijack.custody import expire_hijack_hold, hijacked_at_exceeds_ttl

    state = str(record.get("state") or "")
    if state in {"requested", "stopping"}:
        _reconcile_abandoned_stop_record(project_file, claim, record, log_fn=log_fn)
        return False, held_ttl_days
    if state == "resolving":
        _reconcile_resolving_record(record, log_fn=log_fn)
        return False, held_ttl_days
    if state != "held":
        return False, held_ttl_days
    if is_process_running(claim.pid):
        return False, held_ttl_days
    if held_ttl_days is None:
        held_ttl_days = held_claim_ttl_days()
    hijacked_at = record.get("hijacked_at")
    stamp = hijacked_at if isinstance(hijacked_at, str) else None
    if not hijacked_at_exceeds_ttl(stamp, held_ttl_days):
        return False, held_ttl_days
    try:
        expired = expire_hijack_hold(project_file, claim, record)
    except Exception:
        return False, held_ttl_days
    if not expired:
        return False, held_ttl_days
    settle_stale_retention_record(project_file, claim)
    clear_stale_occupant_record(project_file, claim)
    if log_fn:
        cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
        log_fn(
            f"Released expired hijack workspace #{claim.workspace_num} "
            f"({claim.workflow}){cl_info} - held claim TTL elapsed",
            "cyan",
        )
    return True, held_ttl_days


def _abandoned_stop_is_stale(
    record: dict[str, Any], *, bound_seconds: float = 120.0
) -> bool:
    """Return whether a requested/stopping record outlived its orchestrator.

    The orchestrator advances requested→stopping→held/blocked within
    seconds. A record still in requested/stopping after the bound is
    treated as abandoned (crashed worker, lost response) and reconciled.
    Fail-closed: unreadable timestamps retain.
    """
    from datetime import datetime

    raw = record.get("updated_at") or record.get("hijacked_at")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return False
    try:
        now = (
            datetime.now(tz=stamp.tzinfo)
            if stamp.tzinfo
            else datetime.now(UTC).replace(tzinfo=None)
        )
    except Exception:
        return False
    try:
        age = (now - stamp).total_seconds()
    except Exception:
        return False
    return age >= bound_seconds


def _reconcile_abandoned_stop_record(
    project_file: str,
    claim: WorkspaceClaim,
    record: dict[str, Any],
    *,
    log_fn: Callable[[str, str | None], None] | None = None,
) -> None:
    """Reconcile one abandoned requested/stopping hijack record.

    - Process dead and no hijacked marker: apply the fallback settlement
      (same ``done.json`` the runner would have written) and publish held.
    - Process alive and no orchestrator (stale record): move to
      ``stop_blocked`` so custody stays and ``,k`` retries.

    Best-effort and fail-closed: every failure retains custody.
    """
    try:
        from sase.agent.hijack import ledger
    except Exception:
        return
    try:
        state = str(record.get("state") or "")
        if state not in {"requested", "stopping"}:
            return
        if not _abandoned_stop_is_stale(record):
            return
        hijack_id = record.get("hijack_id")
        if not isinstance(hijack_id, str) or not hijack_id:
            return
        artifacts_dir = record.get("artifacts_dir")
        if not isinstance(artifacts_dir, str) or not artifacts_dir:
            return
        pid = record.get("pid")
        try:
            pid_int = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid_int = None
        alive = False
        if pid_int is not None and pid_int > 1:
            try:
                alive = is_process_running(pid_int)
            except Exception:
                alive = True
        elif claim.pid:
            try:
                alive = is_process_running(int(claim.pid))
            except Exception:
                alive = True
        # Read the settlement marker without taking any lock.
        outcome: str | None = None
        try:
            from pathlib import Path as _Path
            import json as _json

            payload = _json.loads(
                (_Path(artifacts_dir) / "done.json").read_text(encoding="utf-8")
            )
            if isinstance(payload, dict):
                raw_outcome = payload.get("outcome")
                outcome = raw_outcome if isinstance(raw_outcome, str) else None
        except Exception:
            outcome = None
        current = ledger.load_record(hijack_id) or record
        current_state = str(current.get("state") or "")
        if current_state not in {"requested", "stopping"}:
            return
        if not alive:
            # Fallback settlement: the runner died before settling. Write
            # the identical hijacked marker and publish held.
            if outcome != "hijacked":
                try:
                    from sase.agent.hijack._stop_claim import (
                        ensure_hijacked_settlement,
                    )
                    from sase.agent.hijack._stop_models import HijackTarget

                    target = HijackTarget(
                        name=str(current.get("agent_name") or ""),
                        artifacts_dir=artifacts_dir,
                        project_name="",
                        project_file=str(current.get("project_file") or project_file),
                        artifacts_timestamp="",
                        is_home=False,
                        pid=pid_int,
                        claim_pid=None,
                        claim_pinned=True,
                        cl_name=None,
                        workflow=None,
                        workspace_num=current.get("workspace_num")
                        if isinstance(current.get("workspace_num"), int)
                        else claim.workspace_num,
                        workspace_dir=current.get("workspace_dir")
                        if isinstance(current.get("workspace_dir"), str)
                        else None,
                        status="DONE",
                        lifecycle_phase=None,
                        is_monitor_turn=False,
                        is_gate_turn=False,
                        gate_state=None,
                        agent_session=current.get("session")
                        if isinstance(current.get("session"), str)
                        else None,
                        capabilities=[],
                        model_alias=None,
                        model_alias_trail=[],
                        model_origin=None,
                        provider=None,
                        model=None,
                        effort=None,
                        run_started_at=None,
                        done_outcome=None,
                        done_recovery=None,
                    )
                    ensure_hijacked_settlement(target, hijack_id, pinned_by_us=False)
                except Exception:
                    pass
            try:
                if str(current.get("state") or "") == "requested":
                    current = ledger.cas_advance_record(
                        current, {"event": "begin_stop"}
                    )
            except Exception:
                try:
                    current = ledger.load_record(hijack_id) or current
                except Exception:
                    return
                if str(current.get("state") or "") not in {"requested", "stopping"}:
                    return
            try:
                ledger.cas_advance_record(current, {"event": "confirmed_stop"})
            except Exception:
                return
            if log_fn:
                try:
                    log_fn(
                        f"Hijack {hijack_id} settled abandoned stop as held",
                        "cyan",
                    )
                except Exception:
                    pass
            return
        # Process alive but the orchestrator is gone: retain custody in
        # stop_blocked so `,k` retries instead of releasing.
        try:
            if str(current.get("state") or "") == "requested":
                current = ledger.cas_advance_record(current, {"event": "begin_stop"})
        except Exception:
            try:
                current = ledger.load_record(hijack_id) or current
            except Exception:
                return
            if str(current.get("state") or "") not in {"requested", "stopping"}:
                return
        if str(current.get("state") or "") != "stopping":
            return
        try:
            ledger.cas_advance_record(
                current,
                {
                    "event": "stop_blocked",
                    "error": "orchestrator abandoned a live stop",
                },
            )
        except Exception:
            return
        if log_fn:
            try:
                log_fn(
                    f"Hijack {hijack_id} retains workspace (stop_blocked: "
                    "abandoned live stop)",
                    "yellow",
                )
            except Exception:
                pass
    except Exception:
        return


def _reconcile_resolving_record(
    record: dict[str, Any],
    *,
    log_fn: Callable[[str, str | None], None] | None = None,
) -> None:
    """Best-effort reconcile of one resolving hijack record.

    Runs the idempotent recovery reconciliation (adopt the proven
    successor, repair settlement, or return to held when no successor
    exists). Never releases the claim: ``keep_resolving`` and
    ``retain_with_error`` retain custody, and even a successful return to
    held keeps the held claim until its TTL expires. All failures fail
    closed to retention so two cleanup processes cannot duplicate a launch
    or prematurely release a workspace.
    """
    try:
        from sase.agent.hijack.recover_reconcile import reconcile_recovery
    except Exception:
        return
    try:
        decision = reconcile_recovery(record)
    except Exception:
        return
    if log_fn is None or not isinstance(decision, dict):
        return
    try:
        outcome = str(decision.get("outcome") or "")
        if outcome != "retain_with_error":
            return
        code = str(decision.get("code") or "retain")
        message = str(decision.get("message") or "").strip()
        hijack_id = str(record.get("hijack_id") or "unknown")
        detail = f": {message}" if message else ""
        log_fn(f"Hijack {hijack_id} retains workspace ({code}{detail})", "yellow")
    except Exception:
        return


def reconcile_all_resolving_records(
    *,
    log_fn: Callable[[str, str | None], None] | None = None,
) -> None:
    """Reconcile every active resolving record once per sweep.

    Active records are few, so iterating ``list_active_records`` is
    acceptable; scanning ``settled/`` is not. Fail-closed and best-effort.
    """
    try:
        from sase.agent.hijack.ledger import list_active_records
    except Exception:
        return
    try:
        records = list_active_records()
    except Exception:
        return
    for record in records:
        try:
            if not isinstance(record, dict):
                continue
            if str(record.get("state") or "") != "resolving":
                continue
            _reconcile_resolving_record(record, log_fn=log_fn)
        except Exception:
            continue


def drain_pending_settlement_repairs() -> None:
    """Drain a bounded batch of pending repairs once per sweep.

    Runs whether or not any resolving record exists, by authoritative id
    lookup, never a ``settled/`` scan.
    """
    try:
        from sase.agent.hijack.recover_reconcile import repair_pending_settlements
    except Exception:
        return
    try:
        repair_pending_settlements(limit=20)
    except Exception:
        return


def resolving_workspace_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether a resolving recovery pins this workspace.

    Matches by project plus workspace so a claim held by the predecessor
    pid, the reserved successor pid, or a dead successor is never released
    by the generic stale-release path while its record is resolving.
    """
    try:
        from sase.agent.hijack.custody import resolving_record_for_workspace

        return (
            resolving_record_for_workspace(project_file, claim.workspace_num)
            is not None
        )
    except Exception:
        return True
