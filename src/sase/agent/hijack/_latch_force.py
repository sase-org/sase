"""Explicit post-timeout interruption for a pending hijack latch."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from sase.agent.hijack import core, ledger, latch
from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.locks import acquire_hijack_lock


def force_hijack_latch(
    target_key: str,
    *,
    deps: StopDeps | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Stop the identity-matched owner only after explicit force eligibility."""
    deps = deps or StopDeps()
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None and hijack_id:
        record = ledger.load_record(hijack_id)
    if record is None or str(record.get("target_key") or "") != target_key:
        return _action_result(
            "no_latch",
            code="no_latch",
            message="there is no pending hijack latch to force",
            next_action="refresh the agent row and request a hijack if it is still running",
        )
    operation_id = _string(record.get("hijack_id"))
    if hijack_id and operation_id != hijack_id:
        return _action_result(
            "ownership_uncertain",
            code="hijack_id_mismatch",
            message="the pending latch changed since this force action was selected; nothing was signalled",
            record=record,
            target_key=target_key,
            next_action="refresh the agent row and inspect its current pending latch",
        )
    if not operation_id:
        return _action_result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the latch has no operation identity; retain custody",
            record=record,
            next_action="inspect the durable latch record",
        )

    artifacts_dir = _string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return _action_result(
            "ownership_uncertain",
            code="artifacts_dir_missing",
            message="the latch has no owner artifact directory; retain custody",
            record=record,
            next_action="inspect the durable latch record",
        )
    from sase.agent.staged_handoff import acquire_adoption_lock

    with ExitStack() as stack:
        acquired = stack.enter_context(
            acquire_adoption_lock(Path(artifacts_dir), blocking=False)
        )
        if not acquired:
            return _action_result(
                "refused",
                code="adoption_busy",
                message="the owner is settling a handoff; force did not start",
                record=record,
                target_key=target_key,
                next_action="wait for handoff settlement, refresh, then choose Hijack now again",
            )
        stack.enter_context(
            acquire_hijack_lock("apply", _apply_lock_path(operation_id), timeout=30.0)
        )
        current = ledger.load_record(operation_id)
        if (
            current is None
            or str(current.get("hijack_id") or "") != operation_id
            or str(current.get("target_key") or "") != target_key
        ):
            return _action_result(
                "ownership_uncertain",
                code="record_missing",
                message="the latch record changed before force could start; retain custody",
                next_action="refresh the agent row and inspect the active latch",
            )
        state = str(current.get("state") or "")
        if state != "latched":
            return _non_pending_result(current, target_key)

        eligibility = core.hijack_latch_force_eligibility(
            current, latch.current_time(deps)
        )
        if eligibility.get("eligible") is not True:
            code = str(eligibility.get("code") or "force_refused")
            return _action_result(
                "refused",
                code=code,
                message=str(
                    eligibility.get("message") or "the latch cannot be forced yet"
                ),
                record=current,
                target_key=target_key,
                next_action=_force_next_action(code, eligibility),
                age_seconds=eligibility.get("age_seconds"),
                threshold_seconds=eligibility.get("threshold_seconds"),
            )

        name = _string(current.get("agent_name"))
        if not name:
            return _action_result(
                "ownership_uncertain",
                code="owner_name_missing",
                message="the latch has no member identity; retain custody",
                record=current,
                next_action="inspect the durable latch record",
            )
        from sase.agent.hijack.facts import resolve_hijack_subject

        try:
            subject = resolve_hijack_subject(name, deps=deps)
        except Exception as exc:  # noqa: BLE001 - preserve custody on failed resolution.
            return _action_result(
                "ownership_uncertain",
                code="owner_resolution_failed",
                message=f"the current latch owner could not be resolved: {exc}",
                record=current,
                target_key=target_key,
                next_action="refresh the agent list and retry force if the same owner remains",
            )
        target = subject.target
        if target is None:
            return _action_result(
                "refused",
                code="owner_not_live",
                message="the latch owner is no longer available to force; stale recovery will reconcile it",
                record=current,
                target_key=target_key,
                next_action="wait for the stale sweep to reconcile the dead owner",
            )
        identity = latch.owner_identity_for(target)
        if not _same_force_owner(current, target, identity, target_key):
            return _action_result(
                "ownership_uncertain",
                code="owner_identity_mismatch",
                message="the selected member or process no longer matches the pending latch; nothing was signalled",
                record=current,
                target_key=target_key,
                next_action="refresh the agent list and inspect the current occupant",
            )
        selected = getattr(subject, "selected", None)
        if selected is None or not getattr(selected, "process_alive", False):
            return _action_result(
                "refused",
                code="owner_not_live",
                message="the latch owner is no longer live; stale recovery will reconcile it",
                record=current,
                target_key=target_key,
                next_action="wait for the stale sweep to reconcile the dead owner",
            )

        marker_path, intent_error = _persist_force_intent(target, operation_id)
        if intent_error:
            return _action_result(
                "error",
                code="intent_write_failed",
                message=intent_error,
                record=current,
                target_key=target_key,
                next_action="retry after the artifacts directory is writable; no signal was sent",
            )
        pinned_by_us = not bool(target.claim_pinned)
        if not latch.pin_claim(target):
            if marker_path is not None:
                latch.remove_intent(target.artifacts_dir)
            return _action_result(
                "error",
                code="claim_mismatch",
                message="the exact numbered workspace claim could not be held; nothing was signalled",
                record=current,
                target_key=target_key,
                next_action="inspect the workspace claim, then refresh the agent row",
            )

        event: dict[str, Any] = {
            "event": ledger.HIJACK_EVENT_APPLY_LATCH,
            "boundary": "forced_stop",
            "boundary_outcome": "interrupted",
            "forced": True,
        }
        suppressed = _pending_followup(target.artifacts_dir)
        if suppressed is not None:
            event["suppressed_followup"] = suppressed
        try:
            current = ledger.cas_advance_record(current, event)
        except Exception as exc:  # noqa: BLE001 - no signal before durable transition.
            try:
                latest = ledger.load_record(operation_id)
            except Exception:
                latest = None
            if latest is not None and latest.get("state") == "latched":
                if marker_path is not None:
                    latch.remove_intent(target.artifacts_dir)
                if pinned_by_us:
                    latch.unpin_claim(target)
                current = latest
            else:
                # The CAS may have committed even if its caller saw an error.
                # Keep the intent and pin so stale recovery can settle that
                # durable stopping state without losing workspace custody.
                return _action_result(
                    "ownership_uncertain",
                    code="latch_transition_uncertain",
                    message=f"the force transition outcome is uncertain; no signal was sent and workspace custody remains held: {exc}",
                    record=latest or current,
                    target_key=target_key,
                    forced=True,
                    next_action="run the stale sweep and inspect the latch record before retrying",
                )
            return _action_result(
                "error",
                code="latch_transition_failed",
                message=f"the forced latch transition could not be stored; nothing was signalled: {exc}",
                record=ledger.load_record(operation_id) or current,
                target_key=target_key,
                next_action="retry after the latch store is available",
            )

        from sase.agent.hijack._stop_orchestrator_common import (
            build_stop_blocked_result,
            terminate_with_retry,
        )

        try:
            termination = terminate_with_retry(target, deps=deps)
        except Exception as exc:  # noqa: BLE001 - stopping state retains custody.
            return _action_result(
                "applied",
                code="termination_uncertain",
                message=f"forced interruption started, but process termination is uncertain: {exc}",
                record=ledger.load_record(operation_id) or current,
                target_key=target_key,
                next_action="retry the stop from the hijack action; the workspace remains held",
                forced=True,
            )
        if not bool(getattr(termination, "success", False)):
            blocked = build_stop_blocked_result(
                name,
                operation_id,
                current,
                termination,
                subject=subject,
                target=target,
            )
            result = _action_result(
                "applied",
                code="stop_blocked",
                message=blocked.message,
                record=blocked.record,
                target_key=target_key,
                next_action="retry the stop with ,k, or explicitly release with x",
                forced=True,
                survivor_pids=list(getattr(termination, "survivors", ()) or ()),
            )
            return result

        result = latch.complete_latch_application(
            current,
            target,
            target_key=target_key,
            boundary="forced_stop",
            deps=deps,
        )
        result.setdefault("hijack_id", operation_id)
        result.setdefault("target_key", target_key)
        result["forced"] = True
        result["next_action"] = (
            f"inspect the recovery snapshot before continuing with `sase agent recover {name}`"
        )
        return result


def _same_force_owner(
    record: dict[str, Any], target: Any, identity: str | None, target_key: str
) -> bool:
    return (
        bool(identity)
        and str(record.get("owner_identity") or "") == identity
        and latch.same_owner_anchor(record, target, target_key=target_key)
        and str(record.get("project_file") or "") == str(target.project_file)
        and record.get("workspace_num") == target.workspace_num
    )


def _persist_force_intent(
    target: Any, hijack_id: str
) -> tuple[Path | None, str | None]:
    from sase.agent._user_kill_intent import (
        has_user_kill_intent,
        hijack_intent_id,
        user_kill_intent_path,
        write_user_kill_intent,
    )

    marker = user_kill_intent_path(target.artifacts_dir)
    if has_user_kill_intent(target.artifacts_dir):
        if hijack_intent_id(target.artifacts_dir) == hijack_id:
            return None, None
        return (
            None,
            "a different user-kill intent already owns this member; nothing was signalled",
        )
    written = write_user_kill_intent(
        target.artifacts_dir,
        pid=int(target.pid or 0),
        source="agent_hijack",
        reason="explicitly forced pending hijack latch after 120 seconds",
        mode="hijack",
        hijack_id=hijack_id,
    )
    if written is None:
        return (
            None,
            "the forced-stop intent could not be durably written; nothing was signalled",
        )
    return marker, None


def _pending_followup(artifacts_dir: str) -> dict[str, str] | None:
    from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff

    path = Path(artifacts_dir) / STAGED_HANDOFF_FILENAME
    if not path.is_file():
        return None
    try:
        staged = read_staged_handoff(artifacts_dir)
    except Exception:
        return {"kind": "staged", "ref": str(path)}
    if staged is None:
        return None
    kind = staged.get("kind")
    return {
        "kind": kind if isinstance(kind, str) and kind else "staged",
        "ref": str(path),
    }


def _non_pending_result(record: dict[str, Any], target_key: str) -> dict[str, Any]:
    state = str(record.get("state") or "")
    if state == "cancelled":
        return _action_result(
            "cancelled",
            code="latch_cancelled",
            message="the pending hijack latch was cancelled and cannot be forced",
            record=record,
            target_key=target_key,
            next_action="request a new hijack only if the current member still needs one",
        )
    if state == "finished_first":
        return _action_result(
            "moot",
            code="latch_finished_first",
            message="the owner finished before the hijack; nothing was held",
            record=record,
            target_key=target_key,
            next_action="no action is needed",
        )
    if state == "stop_blocked":
        return _action_result(
            "applied",
            code="stop_blocked",
            message="the forced stop is blocked by surviving processes; custody remains held",
            record=record,
            target_key=target_key,
            next_action="retry the stop with ,k, or explicitly release with x",
            forced=bool(record.get("forced")),
        )
    return _action_result(
        "applied",
        code="latch_already_applied",
        message=f"the hijack latch is already {state or 'applied'}",
        record=record,
        target_key=target_key,
        next_action="inspect its recovery record",
        forced=bool(record.get("forced")),
    )


def _force_next_action(code: str, decision: dict[str, Any]) -> str:
    if code == "force_too_early":
        age = decision.get("age_seconds")
        threshold = decision.get("threshold_seconds") or 120
        try:
            remaining = max(0, int(float(threshold) - float(age or 0)))
        except (TypeError, ValueError):
            remaining = 120
        return (
            f"wait {remaining} more seconds, then refresh and choose Hijack now again"
        )
    if code == "clock_before_latch":
        return "wait for a trustworthy clock reading, then refresh the latch"
    if code == "time_unknown":
        return "inspect the latch timestamp; force stays unavailable while its age is unknown"
    return "refresh the agent row and inspect the pending latch"


def _apply_lock_path(hijack_id: str) -> Path:
    return ledger.hijack_record_path(hijack_id).with_suffix(".apply.lock")


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _action_result(
    verdict: str,
    *,
    code: str,
    message: str,
    next_action: str,
    record: dict[str, Any] | None = None,
    target_key: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "code": code,
        "message": message,
        "hijack_id": None if record is None else record.get("hijack_id"),
        "target_key": target_key
        or (None if record is None else record.get("target_key")),
        "record": record,
        "next_action": next_action,
        **fields,
    }


__all__ = ["force_hijack_latch"]
