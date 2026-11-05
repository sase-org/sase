"""Shared types and helpers for staged-handoff host recovery.

Public names in this private module are shared by the recovery split
(``run_agent_exec_staged_recovery*``). Helpers needed by only one recovery
module live in that module instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    read_adoption_receipt,
    receipt_authorizes,
    write_adoption_receipt_locked,
)
from sase.axe._run_agent_exec_staged_shared import read_json_object


@dataclass(frozen=True)
class StagedRecoveryResult:
    """Typed outcome of one host recovery attempt."""

    adopted: bool
    already_adopted: bool
    action: str
    reason: str | None = None
    repair_action: str | None = None
    kind: str | None = None
    origin_agent: str | None = None
    destination: dict[str, Any] | None = None


SUCCESSOR_KINDS = ("pipe", "plan", "questions")


def _held_receipt_payload(staged_id: str, reason: str) -> dict[str, Any]:
    return {
        "staged_id": staged_id,
        "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "outcome": "handoff_not_adopted",
        "reason": reason,
    }


def read_run_metadata(artifacts_dir: str) -> dict[str, Any]:
    return read_json_object(
        Path(artifacts_dir) / "agent_meta.json", label="agent metadata"
    )


def classify_receipt(
    artifacts_dir: str, staged_id: str
) -> tuple[str, dict[str, Any] | None]:
    """Return the Rust receipt wire state plus the receipt when readable."""
    try:
        receipt = read_adoption_receipt(artifacts_dir)
    except StagedHandoffError:
        return "malformed", None
    if receipt is None:
        return "absent", None
    if str(receipt.get("staged_id")) != staged_id:
        return "mismatched", receipt
    try:
        if receipt_authorizes(receipt, staged_id):
            return "adopted", receipt
    except StagedHandoffError:
        return "malformed", receipt
    if receipt.get("outcome") == "handoff_not_adopted":
        return "held", receipt
    return "malformed", receipt


def adopted_destination_refs(
    receipt: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(receipt, Mapping):
        return None
    refs = receipt.get("refs")
    return dict(refs) if isinstance(refs, Mapping) else {}


def adopted_stage_needs_delivery(
    receipt: Mapping[str, Any] | None, kind: str | None
) -> bool:
    """Return whether an adopted stage still needs successor delivery.

    Shared by the recovery service and the stranded-work collector so the
    two definitions cannot drift. Non-successor kinds need no delivery;
    successor kinds (``pipe``/``plan``/``questions``) need it only when the
    adopted receipt names a ``successor_artifacts_dir``.
    """
    if kind not in SUCCESSOR_KINDS:
        return False
    refs = adopted_destination_refs(receipt)
    successor_dir = (refs or {}).get("successor_artifacts_dir")
    return isinstance(successor_dir, str) and bool(successor_dir)


def write_held_locked(staged_id: str, reason: str, *, artifacts_dir: str) -> None:
    from sase.axe.run_agent_exec_staged_monitor import cleanup_staged_monitor_handoff
    from sase.axe.run_agent_exec_staged_retention import retain_dead_staged_origin
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    try:
        retained = read_workspace_retention_record(artifacts_dir)
        if retained is not None and not retained.unresolved:
            return
        receipt_state, _ = classify_receipt(artifacts_dir, staged_id)
        if receipt_state not in {"absent", "held"}:
            return
        retain_dead_staged_origin(staged_id, reason, artifacts_dir=artifacts_dir)
        write_adoption_receipt_locked(
            _held_receipt_payload(staged_id, reason),
            artifacts_dir=artifacts_dir,
        )
    except StagedHandoffError:
        return
    cleanup_staged_monitor_handoff(artifacts_dir, held=True)


def write_adopted_locked(
    *,
    staged_id: str,
    refs: Mapping[str, Any],
    artifacts_dir: str,
) -> None:
    write_adoption_receipt_locked(
        {
            "staged_id": staged_id,
            "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "outcome": "adopted",
            "refs": dict(refs),
        },
        artifacts_dir=artifacts_dir,
    )
    _settle_origin_retention_after_adoption(artifacts_dir)


def _settle_origin_retention_after_adoption(artifacts_dir: str) -> None:
    """Settle a retain record after proven same-workspace adoption.

    A delayed failed-adoption callback must not recreate a hold after this
    success. If the origin still owns the exact claim, the successor did not
    inherit the workspace and the hold stays unresolved.
    """
    try:
        from sase.workspace_provider.retention_record import (
            mark_workspace_retention_settled,
            read_workspace_retention_record,
        )
    except Exception:  # noqa: BLE001 - retention settling is best effort
        return
    record = read_workspace_retention_record(artifacts_dir)
    if record is None or not record.unresolved:
        return
    if _origin_claim_still_held(record):
        return
    mark_workspace_retention_settled(
        artifacts_dir,
        reason="staged_readopt",
        settled_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def _origin_claim_still_held(record: Any) -> bool:
    """Fail closed: unreadable claims are treated as still held."""
    project_file = record.payload.get("project_file")
    if not isinstance(project_file, str) or not project_file:
        return True
    if (
        record.workspace_num is None
        or record.workflow is None
        or record.artifacts_timestamp is None
        or record.pid is None
    ):
        return True
    try:
        from sase.running_field import get_claimed_workspaces

        claims = get_claimed_workspaces(project_file)
    except OSError:
        return True
    return any(
        claim.workspace_num == record.workspace_num
        and claim.workflow == record.workflow
        and (claim.cl_name or "") == (record.cl_name or "")
        and (claim.artifacts_timestamp or "") == record.artifacts_timestamp
        and claim.pid == record.pid
        for claim in claims
    )


__all__ = [
    "SUCCESSOR_KINDS",
    "StagedRecoveryResult",
    "adopted_destination_refs",
    "adopted_stage_needs_delivery",
    "classify_receipt",
    "read_run_metadata",
    "write_adopted_locked",
    "write_held_locked",
]
