"""The ordered stop orchestrator for Agent Hijack (phase ``stop``)."""

from __future__ import annotations

import logging
import socket
import uuid

from sase.agent.hijack._stop_claim import (
    abort_before_stop,
    pin_claim,
    remove_intent,
    unpin_claim,
)
from sase.agent.hijack._stop_models import StopDeps, read_done_marker
from sase.agent.hijack._stop_orchestrator_common import (
    EXIT_FAILED,
    EXIT_HELD,
    EXIT_REFUSED,
    STOP_INTENT_SOURCE,
    HijackStopResult,
    build_stop_blocked_result,
    settle_held_result,
    terminate_with_retry,
)
from sase.agent.hijack._stop_orchestrator_retry import retry_stop_blocked
from sase.agent.hijack._stop_orchestrator_targets import (
    coalesced_result,
    compute_target_key,
    target_identity,
)

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


def _local_host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _read_done_outcome(artifacts_dir: str) -> str | None:
    outcome, _ = read_done_marker(artifacts_dir)
    return outcome


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
    with nothing changed, and 1 means stop failed or an error occurred.
    A second request for the same target returns the active operation
    (same hijack id) instead of starting a second stop.
    """
    deps = deps or StopDeps()
    from sase.agent.hijack.facts import resolve_and_decide

    subject, decision = resolve_and_decide(name, deps=deps)
    target = subject.target

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
        or decision.get("adapter") not in {"llm", "processless"}
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

    record = ledger.new_requested_record(
        hijack_id=resolved_id,
        agent_name=target.name,
        artifacts_dir=target.artifacts_dir,
        pid=target.pid,
        project_file=None if target.is_home else target.project_file,
        workspace_num=target.workspace_num,
        workspace_dir=target.workspace_dir,
        expected_claim_owner_pid=target.claim_pid,
        session=target.agent_session,
        host=_local_host(),
        model_alias=target.model_alias,
        model_alias_trail=target.model_alias_trail,
        model_origin=target.model_origin,
        provider=target.provider,
        model=target.model,
        effort=target.effort,
        target_key=target_key,
        scope=adapter,
    )
    record["prior_pin_state"] = bool(target.claim_pinned)
    try:
        record = ledger.create_record(record)
    except FileExistsError as exc:
        ledger.release_target_slot(target_key, resolved_id)
        return HijackStopResult(
            status="error",
            message=f"Hijack record {resolved_id} already exists: {exc}",
            exit_code=EXIT_FAILED,
            hijack_id=resolved_id,
            reason="record_exists",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    from sase.agent._user_kill_intent import write_user_kill_intent

    intent_path = write_user_kill_intent(
        target.artifacts_dir,
        pid=int(target.pid or 0) if decision.get("adapter") == "llm" else 0,
        source=source,
        reason=reason,
        mode="hijack",
        hijack_id=resolved_id,
    )
    if intent_path is None:
        abort_before_stop(target, resolved_id, reason="intent not persisted")
        ledger.release_target_slot(target_key, resolved_id)
        return HijackStopResult(
            status="error",
            message=(
                f"Cannot hijack agent '{name}': intent was not persisted "
                "before any signal; nothing was signalled"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=resolved_id,
            reason="intent_write_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    pinned_by_us = False
    if not target.is_home and target.workspace_num is not None:
        pin = pin_claim(target)
        if not pin:
            abort_before_stop(
                target, resolved_id, reason="claim mismatch; not hijacked"
            )
            ledger.release_target_slot(target_key, resolved_id)
            return HijackStopResult(
                status="error",
                message=(
                    f"Cannot hijack agent '{name}': its workspace claim changed "
                    f"while preparing; nothing was signalled"
                ),
                exit_code=EXIT_FAILED,
                hijack_id=resolved_id,
                reason="claim_mismatch",
                decision=decision,
                occupant_name=subject.occupant_name,
                occupant_reason=subject.occupant_reason,
                workspace_num=target.workspace_num,
            )
        pinned_by_us = not target.claim_pinned

    try:
        record = ledger.cas_advance_record(record, {"event": "begin_stop"})
    except Exception as exc:
        abort_before_stop(target, resolved_id, reason=str(exc))
        # Restore the pin this attempt set; a prior pin stays pinned.
        if pinned_by_us:
            try:
                unpin_claim(target)
            except Exception:
                pass
        ledger.release_target_slot(target_key, resolved_id)
        return HijackStopResult(
            status="error",
            message=f"Could not start hijack of agent '{name}': {exc}",
            exit_code=EXIT_FAILED,
            hijack_id=resolved_id,
            reason="record_advance_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    # A late wait_checks result must not restart this turn while it is being
    # taken into custody. This only marks the target's own wait; other agents
    # waiting on its hijacked outcome remain parked.
    from sase.axe.run_agent_wait_markers import cancel_waiting_marker_for_hijack

    try:
        wait_cancelled = cancel_waiting_marker_for_hijack(
            target.artifacts_dir,
            resolved_id,
        )
    except Exception as exc:
        wait_cancelled = False
        wait_cancel_error = str(exc)
    else:
        wait_cancel_error = "wait marker was already cancelled by another hijack"
    if not wait_cancelled:
        abort_before_stop(target, resolved_id, reason=wait_cancel_error)
        if pinned_by_us:
            unpin_claim(target)
        ledger.release_target_slot(target_key, resolved_id)
        return HijackStopResult(
            status="error",
            message=(
                f"Cannot hijack agent '{name}': could not cancel its wait marker; "
                "nothing was signalled"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=resolved_id,
            reason="wait_marker_cancel_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    lost = _read_done_outcome(target.artifacts_dir)
    if lost is not None and lost != "hijacked":
        try:
            finished = ledger.cas_advance_record(record, {"event": "finished_first"})
        except Exception:
            finished = ledger.load_record(resolved_id) or record
        remove_intent(target.artifacts_dir)
        if pinned_by_us:
            unpin_claim(target)
        return HijackStopResult(
            status="finished_first",
            message=(
                f"Agent '{name}' finished first ({lost}); its real outcome "
                f"was kept and nothing was stopped"
            ),
            exit_code=EXIT_REFUSED,
            hijack_id=resolved_id,
            record=finished,
            reason="finished_first",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    termination = terminate_with_retry(target, deps=deps) if adapter == "llm" else None
    if termination is not None and not termination.success:
        return build_stop_blocked_result(
            name,
            resolved_id,
            record,
            termination,
            subject=subject,
            target=target,
            decision=decision,
        )

    return settle_held_result(
        name,
        target,
        resolved_id,
        record,
        deps=deps,
        subject=subject,
        decision=decision,
        pinned_by_us=pinned_by_us,
    )


__all__ = [
    "stop_agent_for_hijack",
]
