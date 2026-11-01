"""Post-lock successor delivery for staged-handoff host recovery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    acquire_adoption_lock,
    read_adoption_receipt,
    read_staged_handoff,
    read_staged_successor,
)
from sase.axe._run_agent_exec_staged_recovery_shared import (
    StagedRecoveryResult,
    adopted_destination_refs,
    classify_receipt,
    read_run_metadata,
    write_adopted_locked,
)
from sase.axe.run_agent_exec_staged_custody import (
    mark_custody_transferred,
    persist_origin_custody,
)
from sase.axe.run_agent_successor import (
    SuccessorDeliveryResult,
    deliver_staged_successor_detached,
)


def _delivery_to_held(
    delivery: SuccessorDeliveryResult,
    *,
    kind: str | None,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    destination: dict[str, Any] = {
        "successor_artifacts_dir": delivery.artifacts_dir,
        "successor_agent": delivery.agent_name,
    }
    if delivery.pid is not None:
        destination["pid"] = delivery.pid
    return StagedRecoveryResult(
        adopted=False,
        already_adopted=True,
        action="hold",
        reason=delivery.reason or "adopted successor delivery is pending",
        repair_action=delivery.reason,
        kind=kind,
        origin_agent=origin_agent,
        destination=destination,
    )


def complete_already_adopted_delivery(
    origin: str,
    deferred_already: tuple[dict[str, Any], dict[str, Any] | None],
    *,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    """Finish delivery for a stage whose success receipt already exists."""
    staged_snapshot, receipt_snapshot = deferred_already
    snapshot_id = str(staged_snapshot.get("staged_id") or "")
    snapshot_kind_value = staged_snapshot.get("kind")
    snapshot_kind = (
        str(snapshot_kind_value) if isinstance(snapshot_kind_value, str) else None
    )
    with acquire_adoption_lock(Path(origin)):
        check_agent_value = read_run_metadata(origin).get("name")
        check_agent = (
            str(check_agent_value)
            if isinstance(check_agent_value, str)
            else origin_agent
        )
    delivery = deliver_staged_successor_detached(origin, snapshot_id)
    if delivery.state in {"submitted", "owned", "terminal"}:
        already_destination = adopted_destination_refs(receipt_snapshot) or {}
        already_destination.setdefault(
            "successor_artifacts_dir", delivery.artifacts_dir
        )
        return StagedRecoveryResult(
            adopted=True,
            already_adopted=True,
            action="adopt",
            reason="matching success receipt already owns this adoption",
            kind=snapshot_kind,
            origin_agent=check_agent,
            destination=already_destination,
        )
    return _delivery_to_held(delivery, kind=snapshot_kind, origin_agent=check_agent)


def complete_pending_delivery(
    pending_delivery: tuple[str, str, str | None, str | None],
) -> StagedRecoveryResult:
    """Deliver a recorded successor and write the adoption receipt."""
    pending_origin, pending_staged_id, pending_kind, pending_agent = pending_delivery
    delivery = deliver_staged_successor_detached(pending_origin, pending_staged_id)
    if delivery.state not in {"submitted", "owned", "terminal"}:
        hold_destination: dict[str, Any] = {
            "successor_artifacts_dir": delivery.artifacts_dir,
            "successor_agent": delivery.agent_name,
        }
        if delivery.pid is not None:
            hold_destination["pid"] = delivery.pid
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=delivery.reason or "successor delivery is still pending",
            repair_action=delivery.reason,
            kind=pending_kind,
            origin_agent=pending_agent,
            destination=hold_destination,
        )
    with acquire_adoption_lock(Path(pending_origin)):
        current = read_staged_handoff(pending_origin)
        if current is None or str(current.get("staged_id")) != pending_staged_id:
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="refuse",
                reason="the staged handoff changed during detached delivery",
                kind=pending_kind,
                origin_agent=pending_agent,
            )
        existing_state, _existing = classify_receipt(pending_origin, pending_staged_id)
        if existing_state == "adopted":
            existing = read_adoption_receipt(pending_origin)
            return StagedRecoveryResult(
                adopted=True,
                already_adopted=True,
                action="adopt",
                reason="matching success receipt already owns this adoption",
                kind=pending_kind,
                origin_agent=pending_agent,
                destination=adopted_destination_refs(existing),
            )
        refs: dict[str, Any] = {
            "successor_artifacts_dir": delivery.artifacts_dir,
        }
        try:
            successor_record = read_staged_successor(
                pending_origin, staged_id=pending_staged_id
            )
        except StagedHandoffError:
            successor_record = None
        except Exception:  # noqa: BLE001 - keep the delivered identity.
            successor_record = None
        if successor_record is not None:
            child = successor_record.get("successor", {})
            if isinstance(child, Mapping):
                launch_identity = child.get("launch_identity")
                prompt_ref = child.get("prompt_ref")
                if launch_identity is not None:
                    refs["successor_launch_identity"] = launch_identity
                if prompt_ref is not None:
                    refs["successor_prompt_ref"] = prompt_ref
        try:
            persist_origin_custody(
                current,
                artifacts_dir=pending_origin,
                run_metadata=read_run_metadata(pending_origin),
            )
        except StagedHandoffError:
            pass
        mark_custody_transferred(
            current,
            artifacts_dir=pending_origin,
            carried_to=delivery.artifacts_dir,
        )
        try:
            write_adopted_locked(
                staged_id=pending_staged_id,
                refs=refs,
                artifacts_dir=pending_origin,
            )
        except StagedHandoffError as exc:
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="hold",
                reason=f"detached delivery succeeded but the receipt held: {exc}",
                repair_action="re-run recovery to reconcile the receipt",
                kind=pending_kind,
                origin_agent=pending_agent,
                destination=dict(refs),
            )
        return StagedRecoveryResult(
            adopted=True,
            already_adopted=False,
            action="adopt",
            kind=pending_kind,
            origin_agent=pending_agent,
            destination=dict(refs),
        )


__all__ = [
    "complete_already_adopted_delivery",
    "complete_pending_delivery",
]
