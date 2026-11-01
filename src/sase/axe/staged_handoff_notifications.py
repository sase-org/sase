"""User-facing notices for staged handoffs that recovery could not adopt."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


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

    re_adopt = (
        f"Run `sase agent readopt {origin_name}` to retry after repairing the cause."
        if origin_name
        else "Run `sase agent readopt <origin-agent>` to retry after repairing the cause."
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
                note=f"Staged handoff state is malformed and held. {re_adopt}",
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
        note = (
            f"Staged {kind} handoff {staged_id} for "
            f"{origin_name or 'the originating agent'} was not adopted: {reason}. "
            f"Its staged record and archived proposal are kept. {re_adopt}"
        )
        return _HeldStagedHandoffNotification(staged_id, reason, note)
    except Exception:
        return None
