"""Route stop requests through eligibility, deduplication, and latch handling."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack._stop_orchestrator_common import (
    EXIT_FAILED,
    EXIT_HELD,
    EXIT_LATCHED,
    EXIT_REFUSED,
    STOP_INTENT_SOURCE,
    HijackStopResult,
)
from sase.agent.hijack._stop_orchestrator_retry import retry_stop_blocked
from sase.agent.hijack._stop_orchestrator_settlement import repair_monitor_settlement
from sase.agent.hijack._stop_orchestrator_targets import (
    coalesced_result,
    compute_target_key,
    target_identity,
)
from sase.agent.hijack._stop_orchestrator_transaction import execute_stop_transaction

LOG = logging.getLogger(__name__)

#: Ledger states that keep an active target slot (non-terminal custody).
_ACTIVE_TARGET_STATES = frozenset(
    {"requested", "latched", "stopping", "stop_blocked", "held", "resolving"}
)


def _new_hijack_id(agent_name: str) -> str:
    """Return a filesystem-safe unique id for one hijack attempt."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in agent_name
    ).strip("_")
    return f"hijack-{cleaned or 'agent'}-{uuid.uuid4().hex[:12]}"


def stop_agent_for_hijack(
    name: str,
    *,
    reason: str | None = None,
    hijack_id: str | None = None,
    source: str = STOP_INTENT_SOURCE,
    deps: StopDeps | None = None,
) -> HijackStopResult:
    """Run the ordered stop orchestrator for *name*.

    Exit codes follow the CLI contract: 0 means HIJACKED, 2 means refused
    with nothing changed, 1 means stop failed or an error occurred, and 3
    means the hijack latched and applies at the next safe hand-off.
    A second request for the same target returns the active operation
    (same hijack id) instead of starting a second stop.
    """
    deps = deps or StopDeps()
    from sase.agent.hijack.facts import resolve_and_decide

    subject, decision = resolve_and_decide(name, deps=deps)
    target = subject.target

    if decision.get("mode") == "latched" and target is not None:
        return _request_latch_result(
            name,
            subject,
            target,
            decision,
            hijack_id=hijack_id,
            deps=deps,
        )

    from sase.agent.hijack import ledger

    # Fast-path dedup: when the backend already sees an active hijack for
    # this target, return that operation instead of refusing or doubling
    # the stop. The target key is session-stable so TUI and CLI spellings
    # of the same session coalesce.
    if target is not None:
        try:
            early_key = compute_target_key(subject, target)
            early_active = ledger.find_active_record_by_target_key(early_key)
        except Exception:
            early_key = ""
            early_active = None
        if (
            isinstance(early_active, dict)
            and str(early_active.get("state") or "") in _ACTIVE_TARGET_STATES
        ):
            state = str(early_active.get("state") or "")
            if state == "stop_blocked":
                return retry_stop_blocked(
                    name,
                    early_active,
                    subject=subject,
                    target=target,
                    reason=reason,
                    source=source,
                    deps=deps,
                    decision=decision,
                )
            if state == "stopping" and early_active.get("scope") == "monitor":
                repaired = repair_monitor_settlement(
                    name,
                    early_active,
                    subject=subject,
                    target=target,
                    decision=decision,
                )
                if repaired is not None:
                    return repaired
            if (
                decision.get("code") == "active_hijack"
                or state in _ACTIVE_TARGET_STATES
            ):
                # A concurrent request is already stopping or holding this
                # target; report the same hijack id.
                return coalesced_result(
                    name, early_active, subject=subject, decision=decision
                )

    if (
        decision.get("mode") != "immediate"
        or decision.get("adapter") not in {"llm", "processless", "monitor"}
        or target is None
    ):
        code = str(
            decision.get("code")
            or ("unsupported_adapter" if decision.get("mode") == "immediate" else None)
            or decision.get("mode")
            or "ineligible"
        )
        # A redirect onto an active hijack coalesces onto that operation:
        # both callers report the same hijack id.
        if code in ("active_hijack",) or decision.get("redirect_op") in (
            "show_active_hijack",
        ):
            try:
                fallback_key = (
                    compute_target_key(subject, target) if target is not None else ""
                )
                fallback_active = (
                    ledger.find_active_record_by_target_key(fallback_key)
                    if fallback_key
                    else None
                )
            except Exception:
                fallback_active = None
            if (
                isinstance(fallback_active, dict)
                and str(fallback_active.get("state") or "") in _ACTIVE_TARGET_STATES
            ):
                state = str(fallback_active.get("state") or "")
                if state == "stop_blocked":
                    assert target is not None
                    return retry_stop_blocked(
                        name,
                        fallback_active,
                        subject=subject,
                        target=target,
                        reason=reason,
                        source=source,
                        deps=deps,
                        decision=decision,
                    )
                if state == "stopping" and fallback_active.get("scope") == "monitor":
                    repaired = repair_monitor_settlement(
                        name,
                        fallback_active,
                        subject=subject,
                        target=target,
                        decision=decision,
                    )
                    if repaired is not None:
                        return repaired
                return coalesced_result(
                    name, fallback_active, subject=subject, decision=decision
                )
        message = str(
            decision.get("message")
            or (
                "the selected stop adapter is not supported by this command"
                if decision.get("mode") == "immediate"
                else "hijack was refused"
            )
        )
        return HijackStopResult(
            status="refused",
            message=f"Cannot hijack agent '{name}': {message}",
            exit_code=EXIT_REFUSED,
            reason=code,
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=None if target is None else target.workspace_num,
        )

    target_key = compute_target_key(subject, target)

    resolved_id = hijack_id or _new_hijack_id(name)
    # Claim the target-level slot before creating our record. The winner
    # proceeds; a loser returns the active operation with the same id the
    # winner reports.
    try:
        winner = ledger.claim_target_slot(target_key, resolved_id)
    except Exception:
        winner = resolved_id
    if winner != resolved_id:
        try:
            active = ledger.load_record(winner)
        except Exception:
            active = None
        if (
            isinstance(active, dict)
            and str(active.get("state") or "") not in ledger.TERMINAL_STATES
        ):
            state = str(active.get("state") or "")
            if state == "stop_blocked":
                return retry_stop_blocked(
                    name,
                    active,
                    subject=subject,
                    target=target,
                    reason=reason,
                    source=source,
                    deps=deps,
                    decision=decision,
                )
            if state == "stopping" and active.get("scope") == "monitor":
                repaired = repair_monitor_settlement(
                    name, active, subject=subject, target=target, decision=decision
                )
                if repaired is not None:
                    return repaired
            return coalesced_result(name, active, subject=subject, decision=decision)
        # Stale slot winner: take the slot over and continue.
        try:
            ledger.release_target_slot(target_key, winner)
            winner = ledger.claim_target_slot(target_key, resolved_id)
        except Exception:
            winner = resolved_id
        if winner != resolved_id:
            try:
                active = ledger.load_record(winner)
            except Exception:
                active = None
            if isinstance(active, dict):
                return coalesced_result(
                    name, active, subject=subject, decision=decision
                )
    # Re-resolve immediately before the claim transaction. A session may have
    # advanced since the first decision; never signal a predecessor after its
    # successor becomes the occupant. Do this before creating our own requested
    # ledger record, which the v2 decision correctly treats as an active hijack.
    fresh_subject, fresh_decision = resolve_and_decide(name, deps=deps)
    fresh_target = fresh_subject.target
    identity_changed = (
        fresh_subject.occupant_name != subject.occupant_name
        or target_identity(fresh_target) != target_identity(target)
    )
    decision_changed = (
        fresh_decision != decision
        or fresh_decision.get("mode") != "immediate"
        or fresh_decision.get("eligible") is not True
        or fresh_decision.get("adapter") != decision.get("adapter")
    )
    if identity_changed or decision_changed:
        refusal_code = "occupant_changed" if identity_changed else "decision_changed"
        LOG.info(
            "agent_hijack_decision mode=refused code=%s member=%s requested=%s",
            refusal_code,
            fresh_subject.occupant_name or "-",
            name,
        )
        changed = {
            **fresh_decision,
            "mode": "refused",
            "eligible": False,
            "code": refusal_code,
            "message": (
                "session occupant changed while preparing the hijack"
                if identity_changed
                else "hijack eligibility changed while preparing the stop"
            ),
            "next_action": "explain the session again, then retry if it is still eligible",
        }
        ledger.release_target_slot(target_key, resolved_id)
        return HijackStopResult(
            status="refused",
            message=(
                f"Cannot hijack agent '{name}': {changed['message']}; nothing was signalled"
            ),
            exit_code=EXIT_REFUSED,
            reason=refusal_code,
            decision=changed,
            occupant_name=fresh_subject.occupant_name,
            occupant_reason=fresh_subject.occupant_reason,
            workspace_num=(
                None if fresh_target is None else fresh_target.workspace_num
            ),
        )
    assert fresh_target is not None
    # Use the just-resolved data for the pin/stop transaction. Identity and
    # decision equality above ensure it describes the same eligible target.
    # The target key is session-stable; a re-resolved occupant in the same
    # session keeps the claimed slot.
    target = fresh_target
    subject = fresh_subject
    decision = fresh_decision
    adapter = str(decision.get("adapter"))

    return execute_stop_transaction(
        name,
        target,
        target_key=target_key,
        resolved_id=resolved_id,
        adapter=adapter,
        subject=subject,
        decision=decision,
        deps=deps,
        reason=reason,
        source=source,
    )


def _request_latch_result(
    name: str,
    subject: Any,
    target: Any,
    decision: dict[str, Any],
    *,
    hijack_id: str | None,
    deps: StopDeps,
) -> HijackStopResult:
    """Request or coalesce a latch for a finalizing or staged turn.

    A pending latch never stops the owner or interrupts its finalizer; the
    runner applies it at the next safe boundary. Accepted latches exit 3.
    """
    from sase.agent.hijack import latch as latch_module

    try:
        result = latch_module.request_latch(name, deps=deps, hijack_id=hijack_id)
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=f"Cannot latch hijack for agent '{name}': {exc}",
            exit_code=EXIT_FAILED,
            hijack_id=hijack_id,
            reason="latch_request_failed",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=getattr(target, "workspace_num", None),
        )
    verdict = str(result.get("verdict") or "")
    record = result.get("record")
    record_dict = dict(record) if isinstance(record, dict) else None
    result_hijack_id = result.get("hijack_id")
    hijack_id_str = result_hijack_id if isinstance(result_hijack_id, str) else hijack_id
    if record_dict is None and hijack_id_str:
        try:
            from sase.agent.hijack import ledger as _ledger

            loaded = _ledger.load_record(hijack_id_str)
            if isinstance(loaded, dict):
                record_dict = dict(loaded)
        except Exception:
            pass
    workspace_num = getattr(target, "workspace_num", None)
    occupant_name = getattr(subject, "occupant_name", None)
    occupant_reason = getattr(subject, "occupant_reason", None)
    boundary = decision.get("boundary") or result.get("boundary")
    boundary_text = (
        str(boundary).replace("_", " ")
        if isinstance(boundary, str) and boundary
        else "hand-off"
    )
    if verdict == "pending":
        return HijackStopResult(
            status="latched",
            message=(
                f"\u23cf hijack latched for {occupant_name or name} "
                f"\u00b7 applies after {boundary_text} "
                f"\u00b7 next: sase agent hijack -c {name} to cancel"
            ),
            exit_code=EXIT_LATCHED,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or decision.get("code") or "latched"),
            decision=decision,
            occupant_name=occupant_name,
            occupant_reason=occupant_reason,
            workspace_num=workspace_num,
        )
    if verdict in {"applied", "moot"}:
        state = str((record_dict or {}).get("state") or verdict)
        return HijackStopResult(
            status=state,
            message=str(result.get("message") or f"hijack latch is {verdict}"),
            exit_code=EXIT_HELD if verdict == "applied" else EXIT_REFUSED,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict),
            decision=decision,
            occupant_name=occupant_name,
            occupant_reason=occupant_reason,
            workspace_num=workspace_num,
        )
    if verdict == "cancelled":
        return HijackStopResult(
            status="cancelled",
            message=str(result.get("message") or "the pending hijack was cancelled"),
            exit_code=EXIT_HELD,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or "cancelled"),
            decision=decision,
            occupant_name=occupant_name,
            occupant_reason=occupant_reason,
            workspace_num=workspace_num,
        )
    if verdict in {"refused", "no_latch", "ownership_uncertain"}:
        return HijackStopResult(
            status="refused",
            message=(
                f"Cannot latch hijack for agent '{name}': "
                f"{result.get('message') or 'latch was refused'}"
            ),
            exit_code=EXIT_REFUSED,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict or "latch_refused"),
            decision=decision,
            occupant_name=occupant_name,
            occupant_reason=occupant_reason,
            workspace_num=workspace_num,
        )
    return HijackStopResult(
        status="error",
        message=(
            f"Cannot latch hijack for agent '{name}': "
            f"{result.get('message') or 'latch request failed'}"
        ),
        exit_code=EXIT_FAILED,
        hijack_id=hijack_id_str,
        record=record_dict,
        reason=str(result.get("code") or "latch_request_failed"),
        decision=decision,
        occupant_name=occupant_name,
        occupant_reason=occupant_reason,
        workspace_num=workspace_num,
    )
