"""The ordered stop protocol for Agent Hijack (phase ``stop``)."""

from __future__ import annotations

import logging
import socket
import uuid
from dataclasses import dataclass
from typing import Any

from sase.agent.hijack._stop_claim import (
    abort_before_stop,
    ensure_hijacked_settlement,
    pin_claim,
    remove_intent,
    terminate_tree,
    unpin_claim,
)
from sase.agent.hijack._stop_evidence import (
    collect_and_attach_evidence,
    format_diff_summary,
)
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_done_marker

LOG = logging.getLogger(__name__)

#: Source tag recorded in the user-kill intent marker.
STOP_INTENT_SOURCE = "agent_hijack"

_EXIT_HELD = 0
_EXIT_REFUSED = 2
_EXIT_FAILED = 1

#: Bounded termination retries after the first attempt before custody
#: falls back to ``stop_blocked``. The verified terminator already
#: escalates SIGTERM to SIGKILL internally; the bound covers a second and
#: third pass for late-spawning children.
_STOP_RETRY_ATTEMPTS = 2

#: Ledger states that keep an active target slot (non-terminal custody).
_ACTIVE_TARGET_STATES = frozenset(
    {"requested", "latched", "stopping", "stop_blocked", "held", "resolving"}
)


@dataclass
class HijackStopResult:
    """Outcome of one stop-orchestrator run."""

    status: str
    message: str
    exit_code: int
    hijack_id: str | None = None
    record: dict[str, Any] | None = None
    reason: str | None = None
    decision: dict[str, Any] | None = None
    occupant_name: str | None = None
    occupant_reason: str | None = None
    workspace_num: int | None = None


def _new_hijack_id(agent_name: str) -> str:
    """Return a filesystem-safe unique id for one hijack attempt."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in agent_name
    ).strip("_")
    return f"hijack-{cleaned or 'agent'}-{uuid.uuid4().hex[:12]}"


def _target_key_name(subject: Any, target: HijackTarget) -> str:
    """Return the session-or-agent name component of the target key."""
    session = getattr(subject, "session", None)
    base_name = getattr(session, "base_name", None)
    if isinstance(base_name, str) and base_name:
        return base_name
    agent_session = getattr(target, "agent_session", None)
    if isinstance(agent_session, str) and agent_session:
        return agent_session
    return target.name


def _compute_target_key(subject: Any, target: HijackTarget) -> str:
    from sase.agent.hijack import ledger

    project_file: str | None = None
    if not target.is_home:
        project_file = target.project_file
    return ledger.target_key_for(project_file, _target_key_name(subject, target))


def _coalesced_result(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    decision: dict[str, Any] | None = None,
) -> HijackStopResult:
    """Return the active operation instead of starting a second stop."""
    state = str(active.get("state") or "")
    hijack_id = active.get("hijack_id")
    hijack_id_str = hijack_id if isinstance(hijack_id, str) else None
    workspace_num = active.get("workspace_num")
    try:
        workspace_num_int = int(workspace_num) if workspace_num is not None else None
    except (TypeError, ValueError):
        workspace_num_int = None
    if state == "held":
        return HijackStopResult(
            status="held",
            message=(
                f"Hijack {hijack_id_str} already holds "
                f"{active.get('agent_name') or name}; nothing else was stopped"
            ),
            exit_code=_EXIT_HELD,
            hijack_id=hijack_id_str,
            record=dict(active),
            reason="already_held",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=workspace_num_int,
        )
    if state == "stop_blocked":
        survivors = active.get("survivor_pids") or []
        detail = ""
        try:
            count = len(list(survivors))
            if count:
                detail = f" ({count} processes survived)"
        except TypeError:
            detail = ""
        return HijackStopResult(
            status="stop_blocked",
            message=(
                f"Hijack {hijack_id_str} is already blocked{detail}; "
                "workspace kept; `,k` retries, or release with x"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=hijack_id_str,
            record=dict(active),
            reason="stop_blocked",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=workspace_num_int,
        )
    return HijackStopResult(
        status="active",
        message=(
            f"Hijack {hijack_id_str} is already {state or 'in progress'}; "
            "returning the active operation instead of starting a second stop"
        ),
        exit_code=_EXIT_HELD,
        hijack_id=hijack_id_str,
        record=dict(active),
        reason="already_active",
        decision=decision,
        occupant_name=getattr(subject, "occupant_name", None),
        occupant_reason=getattr(subject, "occupant_reason", None),
        workspace_num=workspace_num_int,
    )


def _terminate_with_retry(target: HijackTarget, *, deps: StopDeps) -> Any:
    """Run the verified terminator, retrying a bounded number of times.

    The terminator escalates SIGTERM to SIGKILL internally. A retry covers
    children that appeared while the tree shut down.
    """
    termination = terminate_tree(target, deps=deps)
    attempts = 0
    while not termination.success and attempts < _STOP_RETRY_ATTEMPTS:
        attempts += 1
        LOG.warning(
            "hijack termination retry %d for %s: %s",
            attempts,
            target.name,
            getattr(termination, "error", None) or "survivors remain",
        )
        termination = terminate_tree(target, deps=deps)
    return termination


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
            early_key = _compute_target_key(subject, target)
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
                return _retry_stop_blocked(
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
                return _coalesced_result(
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
                    _compute_target_key(subject, target) if target is not None else ""
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
                    return _retry_stop_blocked(
                        name,
                        fallback_active,
                        subject=subject,
                        target=target,
                        reason=reason,
                        source=source,
                        deps=deps,
                        decision=decision,
                    )
                return _coalesced_result(
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
            exit_code=_EXIT_REFUSED,
            reason=code,
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=None if target is None else target.workspace_num,
        )

    target_key = _compute_target_key(subject, target)

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
                return _retry_stop_blocked(
                    name,
                    active,
                    subject=subject,
                    target=target,
                    reason=reason,
                    source=source,
                    deps=deps,
                    decision=decision,
                )
            return _coalesced_result(name, active, subject=subject, decision=decision)
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
                return _coalesced_result(
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
        or _target_identity(fresh_target) != _target_identity(target)
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
            exit_code=_EXIT_REFUSED,
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
            exit_code=_EXIT_FAILED,
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
            exit_code=_EXIT_FAILED,
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
                exit_code=_EXIT_FAILED,
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
            exit_code=_EXIT_FAILED,
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
            exit_code=_EXIT_FAILED,
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
            exit_code=_EXIT_REFUSED,
            hijack_id=resolved_id,
            record=finished,
            reason="finished_first",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    termination = _terminate_with_retry(target, deps=deps) if adapter == "llm" else None
    if termination is not None and not termination.success:
        survivors = [int(pid) for pid in (termination.survivors or ())]
        # Bounded retries are exhausted; retain custody in stop_blocked so
        # the workspace stays pinned and `,k` can retry. Only an explicit
        # abandon releases the claim.
        try:
            blocked = ledger.cas_advance_record(
                record,
                {
                    "event": "stop_blocked",
                    "error": termination.error or f"survivor pids: {survivors}",
                },
            )
            try:
                merged = ledger.merge_record_fields(
                    resolved_id, {"survivor_pids": survivors}
                )
                if isinstance(merged, dict):
                    blocked = merged
            except Exception:
                pass
        except Exception:
            blocked = ledger.load_record(resolved_id) or record
        detail = f" ({len(survivors)} processes survived)" if survivors else ""
        return HijackStopResult(
            status="stop_blocked",
            message=(
                f"Could not fully stop agent '{name}'{detail}; workspace kept; "
                "`,k` retries, or release with x"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            record=blocked,
            reason="stop_blocked",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )

    ensure_hijacked_settlement(target, resolved_id, pinned_by_us)
    try:
        record = ledger.load_record(resolved_id) or record
    except Exception:
        pass
    record_after_evidence, evidence_error, _snapshot_error = (
        collect_and_attach_evidence(resolved_id, target, deps=deps)
    )
    record = record_after_evidence or ledger.load_record(resolved_id) or record
    try:
        held = ledger.cas_advance_record(record, {"event": "confirmed_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=(
                f"Agent '{name}' was stopped but the hijack record could not "
                f"be published: {exc}"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=resolved_id,
            record=ledger.load_record(resolved_id) or record,
            reason="publish_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    summary = format_diff_summary(held)
    held_suffix = f" · {summary}" if summary else ""
    if evidence_error:
        held_suffix += f" (snapshot pending: {evidence_error})"
    return HijackStopResult(
        status="held",
        message=(
            f"\u23cf hijacked {target.name} \u00b7 ws #{target.workspace_num} held"
            f"{held_suffix} \u00b7 next: sase agent recover {target.name}"
        ),
        exit_code=_EXIT_HELD,
        hijack_id=resolved_id,
        record=held,
        decision=decision,
        occupant_name=subject.occupant_name,
        occupant_reason=subject.occupant_reason,
        workspace_num=target.workspace_num,
    )


def _retry_stop_blocked(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    target: HijackTarget,
    reason: str | None,
    source: str,
    deps: StopDeps,
    decision: dict[str, Any] | None = None,
) -> HijackStopResult:
    """Retry a ``stop_blocked`` target without starting a second stop."""
    from sase.agent.hijack import ledger

    hijack_id = str(active.get("hijack_id") or "")
    try:
        record = ledger.cas_advance_record(active, {"event": "retry_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=f"Could not retry hijack of agent '{name}': {exc}",
            exit_code=_EXIT_FAILED,
            hijack_id=hijack_id or None,
            record=ledger.load_record(hijack_id) if hijack_id else active,
            reason="retry_failed",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=target.workspace_num,
        )
    termination = _terminate_with_retry(target, deps=deps)
    if not termination.success:
        survivors = [int(pid) for pid in (termination.survivors or ())]
        try:
            blocked = ledger.cas_advance_record(
                record,
                {
                    "event": "stop_blocked",
                    "error": termination.error or f"survivor pids: {survivors}",
                },
            )
            try:
                merged = ledger.merge_record_fields(
                    hijack_id, {"survivor_pids": survivors}
                )
                if isinstance(merged, dict):
                    blocked = merged
            except Exception:
                pass
        except Exception:
            blocked = ledger.load_record(hijack_id) or record
        detail = f" ({len(survivors)} processes survived)" if survivors else ""
        return HijackStopResult(
            status="stop_blocked",
            message=(
                f"Could not fully stop agent '{name}'{detail}; workspace kept; "
                "`,k` retries, or release with x"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=hijack_id,
            record=blocked,
            reason="stop_blocked",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=target.workspace_num,
        )
    # Retry succeeded: fall through to the normal held settlement.
    ensure_hijacked_settlement(target, hijack_id, pinned_by_us=False)
    try:
        current = ledger.load_record(hijack_id) or record
    except Exception:
        current = record
    record_after_evidence, _evidence_error, _snapshot_error = (
        collect_and_attach_evidence(
            hijack_id,
            target,
            deps=deps,
            record_snapshot_error=False,
        )
    )
    current = record_after_evidence or ledger.load_record(hijack_id) or current
    try:
        held = ledger.cas_advance_record(current, {"event": "confirmed_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=(
                f"Agent '{name}' was stopped but the hijack record could not "
                f"be published: {exc}"
            ),
            exit_code=_EXIT_FAILED,
            hijack_id=hijack_id,
            record=ledger.load_record(hijack_id) or current,
            reason="publish_failed",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=target.workspace_num,
        )
    summary = format_diff_summary(held)
    held_suffix = f" · {summary}" if summary else ""
    return HijackStopResult(
        status="held",
        message=(
            f"\u23cf hijacked {target.name} \u00b7 ws #{target.workspace_num} held"
            f"{held_suffix} \u00b7 next: sase agent recover {target.name}"
        ),
        exit_code=_EXIT_HELD,
        hijack_id=hijack_id,
        record=held,
        decision=decision,
        occupant_name=getattr(subject, "occupant_name", None),
        occupant_reason=getattr(subject, "occupant_reason", None),
        workspace_num=target.workspace_num,
    )


def _local_host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _read_done_outcome(artifacts_dir: str) -> str | None:
    outcome, _ = read_done_marker(artifacts_dir)
    return outcome


def _target_identity(target: HijackTarget | None) -> tuple[Any, ...] | None:
    if target is None:
        return None
    return (
        target.name,
        target.project_file,
        target.artifacts_timestamp,
        target.artifacts_dir,
        target.pid,
        target.claim_pid,
        target.workspace_num,
        target.agent_session,
        target.is_home,
    )


__all__ = [
    "HijackStopResult",
    "STOP_INTENT_SOURCE",
    "stop_agent_for_hijack",
]
