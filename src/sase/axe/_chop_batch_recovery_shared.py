"""Shared data and notifications for chop batch recovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.core.time import get_timezone


@dataclass(frozen=True)
class ChopBatchRecoveryResult:
    """Outcome of attempting recovery for one stored batch."""

    routine: str
    job: str
    batch_id: str
    kind: str  # "ordinary", "typed", "skipped", "blocked", "cancelled"
    launched: tuple[Any, ...] = ()
    already_launched: tuple[int, ...] = ()
    blocked: tuple[dict[str, Any], ...] = ()
    paused: bool = False
    reason: str | None = None


def batch_needs_resume(manifest: Mapping[str, Any]) -> bool:
    """Return whether a manifest still owns pending dispatch work."""
    status = str(manifest.get("status") or "open")
    if status in {"cancelled", "complete"}:
        return False
    members = manifest.get("members")
    if not isinstance(members, list):
        return False
    return any(
        str(item.get("status") or "pending") in {"pending", "dispatching"}
        for item in members
        if isinstance(item, Mapping)
    )


def batch_clan(manifest: Mapping[str, Any]) -> str | None:
    """Return the clan name recorded on a batch or one of its members."""
    for key in ("clan", "clan_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    members = manifest.get("members")
    if isinstance(members, list):
        for member in members:
            if isinstance(member, Mapping):
                clan = member.get("clan")
                if isinstance(clan, str) and clan:
                    return clan
    return None


def emit_batch_notice(
    *,
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    launched: int,
    remaining: int,
    clan: str | None = None,
) -> None:
    """Append a deduplicated run log line and notification for one batch event."""
    timestamp = datetime.now(get_timezone()).isoformat()
    clan_part = f" clan {clan}" if clan else ""
    line = (
        f"Chop batch {event}: routine {routine} job {job} run {batch_id}{clan_part}: "
        f"{launched} launched, {remaining} remaining (at {timestamp}).\n"
    )
    try:
        from .state import append_chop_run_output

        append_chop_run_output(routine, job, batch_id, line)
    except Exception:
        pass
    try:
        from uuid import uuid4

        from sase.notifications.models import Notification
        from sase.notifications.store import upsert_notification

        dedup_key = f"chop-batch:{event}:{routine}:{job}:{batch_id}"
        notes = [
            f"Chop launch batch {event}: {routine}/{job} run {batch_id}.",
            f"{launched} launched, {remaining} remaining.",
        ]
        if clan:
            notes.append(f"Clan: {clan}.")
        if event == "interrupted":
            notes.append("The batch will resume automatically on the next tick.")
        elif event == "resumed":
            notes.append("Remaining members resumed under their original identities.")
        elif event == "cancelled":
            notes.append(
                "Remaining launch intent was discarded by an explicit clan kill."
            )
        notification = Notification(
            id=str(uuid4()),
            timestamp=timestamp,
            sender="chop-batch-recovery",
            icon="!",
            color="#D14343" if event in {"interrupted", "cancelled"} else "#2E7D32",
            notes=notes,
            files=[],
            tags=["chop", "batch", event],
            dedup_key=dedup_key,
        )
        upsert_notification(
            notification,
            plus_one_note=f"Still {event}",
            plus_one_timestamp=timestamp,
        )
    except Exception:
        pass
