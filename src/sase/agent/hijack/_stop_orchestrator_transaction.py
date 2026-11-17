"""Create the hijack record, stop the target, and settle custody."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_claim import (
    abort_before_stop,
    pin_claim,
    remove_intent,
    unpin_claim,
)
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_done_marker
from sase.agent.hijack._stop_orchestrator_common import (
    EXIT_FAILED,
    EXIT_REFUSED,
    HijackStopResult,
    build_stop_blocked_result,
    settle_held_result,
    terminate_with_retry,
)
from sase.agent.hijack._stop_orchestrator_targets import coalesced_result


def _local_host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _read_done_outcome(artifacts_dir: str) -> str | None:
    outcome, _ = read_done_marker(artifacts_dir)
    return outcome


def execute_stop_transaction(
    name: str,
    target: HijackTarget,
    *,
    target_key: str,
    resolved_id: str,
    adapter: str,
    subject: Any,
    decision: dict[str, Any],
    deps: StopDeps,
    reason: str | None,
    source: str,
) -> HijackStopResult:
    """Claim, stop, and settle one already-validated target."""
    from sase.agent.hijack import ledger

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
