"""The ordered stop orchestrator for Agent Hijack (phase ``stop``)."""

from __future__ import annotations

import logging
import os
import socket
import uuid
from pathlib import Path
from typing import Any

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
    EXIT_LATCHED,
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
        pid=(
            int(target.pid or 0) if decision.get("adapter") in {"llm", "monitor"} else 0
        ),
        source=source,
        reason=reason,
        mode="hijack",
        hijack_id=resolved_id,
        custody_pid=os.getpid() if decision.get("adapter") == "monitor" else None,
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

    termination = (
        terminate_with_retry(target, deps=deps)
        if adapter in {"llm", "monitor"}
        else None
    )
    if termination is not None and not termination.success:
        if adapter == "monitor":
            settled = ledger.load_record(resolved_id)
            if isinstance(settled, dict) and settled.get("state") == "held":
                return coalesced_result(
                    name, settled, subject=subject, decision=decision
                )
        return build_stop_blocked_result(
            name,
            resolved_id,
            record,
            termination,
            subject=subject,
            target=target,
            decision=decision,
        )

    if adapter == "monitor":
        monitor_record = getattr(termination, "monitor_record", None)
        monitor_state = getattr(monitor_record, "monitor_state", None)
        if not isinstance(monitor_state, str) or monitor_state == "running":
            return build_stop_blocked_result(
                name,
                resolved_id,
                record,
                termination,
                subject=subject,
                target=target,
                decision=decision,
            )
        from sase.agent.hijack._stop_models import read_json_dict
        from sase.monitor.hijack_settlement import settle_monitor_hijack

        meta = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
        settlement = settle_monitor_hijack(
            target.artifacts_dir,
            meta,
            monitor_state=monitor_state,
            project_name=target.project_name,
        )
        current = ledger.load_record(resolved_id) or record
        if not settlement.settled or current.get("state") != "held":
            return HijackStopResult(
                status="settlement_pending",
                message=(
                    f"Monitor {target.name} stopped, but hijack settlement remains "
                    f"repairable: {settlement.error or current.get('error') or 'pending'}"
                ),
                exit_code=EXIT_FAILED,
                hijack_id=resolved_id,
                record=current,
                reason="settlement_pending",
                decision=decision,
                occupant_name=subject.occupant_name,
                occupant_reason=subject.occupant_reason,
                workspace_num=target.workspace_num,
            )
        return coalesced_result(name, current, subject=subject, decision=decision)

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


def repair_monitor_settlement(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    target: Any,
    decision: dict[str, Any],
) -> HijackStopResult | None:
    """Replay a terminal monitor checkpoint after a prior partial settle."""
    from sase.agent.hijack._stop_models import read_json_dict
    from sase.agent.hijack._stop_orchestrator_targets import coalesced_result
    from sase.monitor.hijack_settlement import settle_monitor_hijack
    from sase.monitor.store import read_monitor_marker

    current = read_monitor_marker(target.project_name, target.artifacts_dir)
    if current is None or current.monitor_state == "running":
        return None
    meta = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    disposition = settle_monitor_hijack(
        target.artifacts_dir,
        meta,
        monitor_state=current.monitor_state,
        project_name=target.project_name,
    )
    record = None
    try:
        from sase.agent.hijack import ledger

        record = ledger.load_record(str(active.get("hijack_id") or ""))
    except Exception:
        pass
    if (
        disposition.settled
        and isinstance(record, dict)
        and record.get("state") == "held"
    ):
        return coalesced_result(name, record, subject=subject, decision=decision)
    if disposition.handled:
        return HijackStopResult(
            status="settlement_pending",
            message=(
                f"Monitor {target.name} is terminal, but hijack settlement remains "
                f"repairable: {disposition.error or 'pending'}"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=str(active.get("hijack_id") or "") or None,
            record=record or active,
            reason="settlement_pending",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=getattr(target, "workspace_num", None),
        )
    return None


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


__all__ = [
    "stop_agent_for_hijack",
]
