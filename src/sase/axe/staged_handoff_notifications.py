"""User-facing notices for staged handoffs that recovery could not adopt."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _HeldStagedHandoffNotification:
    """Rendered hold notice plus the receipt identity used for deduplication."""

    staged_id: str
    reason: str
    note: str


def held_staged_handoff_notification(
    current_artifacts_dir: str,
    *,
    include_malformed_receipt: bool = False,
    require_current_stage: bool = False,
) -> _HeldStagedHandoffNotification | None:
    """Build the existing runner note for a held staged handoff.

    Recovery notifications require a current, matching staged record. The
    runner keeps its historical malformed-receipt wording by opting into the
    malformed receipt notice.
    """
    origin_name = None
    try:
        with open(
            os.path.join(current_artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            origin_meta = json.load(f)
        if isinstance(origin_meta, dict):
            raw_name = origin_meta.get("name") or origin_meta.get("agent_name")
            if isinstance(raw_name, str) and raw_name:
                origin_name = raw_name
    except (json.JSONDecodeError, OSError):
        pass

    readopt_command = (
        f"Run `sase agent readopt {origin_name}` to retry after repairing the cause."
        if origin_name
        else "Run `sase agent readopt <origin-agent>` to retry after repairing the cause."
    )
    salvage = (
        "This handoff cannot be re-adopted from its saved state. Salvage the "
        "workspace's work, then dismiss this agent to release it."
    )
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )

        try:
            receipt = read_adoption_receipt(current_artifacts_dir)
        except StagedHandoffError:
            if not include_malformed_receipt:
                return None
            return _HeldStagedHandoffNotification(
                staged_id="malformed",
                reason="malformed",
                note=f"Staged handoff state is malformed and held. {salvage}",
            )
        except Exception:
            return None
        if receipt is None or receipt.get("outcome") != "handoff_not_adopted":
            return None

        record_malformed = False
        try:
            record = read_staged_handoff(current_artifacts_dir)
        except StagedHandoffError:
            record = None
            record_malformed = True
        except Exception:
            return None
        if record_malformed:
            kind = "malformed"
            record_id: str | None = None
        elif record is None:
            kind = "unknown"
            record_id = None
        else:
            raw_kind = record.get("kind")
            kind = raw_kind if isinstance(raw_kind, str) and raw_kind else "unknown"
            raw_record_id = record.get("staged_id")
            record_id = (
                raw_record_id
                if isinstance(raw_record_id, str) and raw_record_id
                else None
            )

        raw_staged_id = receipt.get("staged_id")
        receipt_id = (
            raw_staged_id if isinstance(raw_staged_id, str) and raw_staged_id else None
        )
        staged_id = receipt_id or record_id or "unknown"
        if require_current_stage and (
            record_id is None
            or record_malformed
            or (receipt_id is not None and receipt_id != record_id)
        ):
            return None

        raw_reason = receipt.get("reason")
        reason = (
            raw_reason
            if isinstance(raw_reason, str) and raw_reason.strip()
            else "unknown reason"
        )
        can_readopt = _can_readopt_staged_handoff(
            current_artifacts_dir,
            staged_id=staged_id,
            kind=kind,
            record=record,
            record_malformed=record_malformed,
            receipt_id=receipt_id,
            record_id=record_id,
        )
        remedy = readopt_command if can_readopt else salvage
        preserved = (
            "Its staged record and archived proposal are kept. "
            if record is not None and not record_malformed
            else ""
        )
        note = (
            f"Staged {kind} handoff {staged_id} for "
            f"{origin_name or 'the originating agent'} was not adopted: {reason}. "
            f"{preserved}{remedy}"
        )
        return _HeldStagedHandoffNotification(staged_id, reason, note)
    except Exception:
        return None


def _can_readopt_staged_handoff(
    artifacts_dir: str,
    *,
    staged_id: str,
    kind: str,
    record: dict[str, object] | None,
    record_malformed: bool,
    receipt_id: str | None,
    record_id: str | None,
) -> bool:
    """Return whether saved evidence supports a real readopt retry."""
    if (
        record is None
        or record_malformed
        or kind not in {"gate", "monitor", "pipe", "plan", "questions"}
        or not record_id
        or (receipt_id is not None and receipt_id != record_id)
    ):
        return False

    try:
        from sase.agent.staged_handoff import (
            read_provider_failure_record,
            read_staged_handoff_response,
        )

        response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
        has_failure = read_provider_failure_record(artifacts_dir) is not None
    except Exception:  # noqa: BLE001 - uncertain recovery evidence means salvage.
        return False
    if response is None and not has_failure:
        return False

    if kind != "monitor":
        return True
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    monitor_id = payload.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        return False
    try:
        from sase.monitor.staged_owner import (
            launch_payload_path,
            staged_monitor_member_artifacts_dir,
        )

        member_dir = staged_monitor_member_artifacts_dir(monitor_id, staged_id, payload)
        return bool(
            member_dir
            and Path(member_dir).is_dir()
            and launch_payload_path(member_dir).is_file()
        )
    except Exception:  # noqa: BLE001 - uncertain member custody means salvage.
        return False
