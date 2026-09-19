"""Best-effort notifications for durable agent-hold lifecycle events."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sase.core.agent_hold_store import format_epoch, mapping_payload
from sase.core.agent_hold_types import PendingCapture

LOGGER = logging.getLogger(__name__)

AGENT_HOLD_SENDER = "agent_hold"


def upsert_hold_armed_notification(
    record: Mapping[str, Any],
    capture: PendingCapture | None,
    *,
    now: datetime | float | None,
) -> None:
    from uuid import uuid4

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    armer = mapping_payload(record.get("armer"))
    key = armer.get("key")
    if not isinstance(key, str) or not key:
        return
    display = armer.get("display") or key
    timestamp = _iso_timestamp(now)
    notes = [
        f"Armed by {display}",
        f"Expires: {format_epoch(record.get('expires_at'))}",
    ]
    if capture is not None:
        notes.append(
            f"Captured {len(capture.artifact_dirs)} pending "
            f"({capture.waiting_count} waiting, {capture.queued_count} queued); "
            f"skipped {capture.skipped_running_count} running"
        )
    try:
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=timestamp,
                sender=AGENT_HOLD_SENDER,
                icon="⏸",
                color="#5F87FF",
                notes=notes,
                tags=normalize_notification_tags(["agent-hold", "armed"]),
                action_data={
                    "armer_key": key,
                    "expires_at": str(record.get("expires_at")),
                },
                dedup_key=f"agent_hold:armed:{key}",
            ),
            plus_one_note="Re-armed",
            plus_one_timestamp=timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort.
        LOGGER.warning("agent hold armed notification failed for %s: %s", key, exc)


def upsert_hold_released_notification(
    armer: Mapping[str, Any],
    *,
    reason: str,
    now: datetime | float | None,
) -> None:
    from uuid import uuid4

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    key = armer.get("key")
    if not isinstance(key, str) or not key:
        return
    display = armer.get("display") or key
    timestamp = _iso_timestamp(now)
    try:
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=timestamp,
                sender=AGENT_HOLD_SENDER,
                icon="▶",
                color="#5FAF5F",
                notes=[f"Released: {display}", reason],
                tags=normalize_notification_tags(["agent-hold", "released"]),
                action_data={"armer_key": key},
                dedup_key=f"agent_hold:released:{key}",
            ),
            plus_one_note=f"Released again: {reason}",
            plus_one_timestamp=timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort.
        LOGGER.warning("agent hold released notification failed for %s: %s", key, exc)


def notify_hold_prune_outcomes(
    pruned: Sequence[Mapping[str, Any]],
    *,
    now: datetime | float | None,
) -> None:
    """Notify for validated store-boundary prune outcomes.

    Deduped by armer key for the hold's lifetime. Best-effort: a notification
    failure never becomes an admission failure.
    """
    for item in pruned:
        record = item.get("record")
        if not isinstance(record, Mapping):
            continue
        try:
            armer = mapping_payload(record.get("armer"))
        except RuntimeError:
            continue
        reason = item.get("reason")
        if reason == "expiry":
            text = "Released automatically: hold expired"
        elif reason == "dead_armer":
            text = "Released automatically: armer no longer alive"
        else:
            continue
        upsert_hold_released_notification(armer, reason=text, now=now)


def _iso_timestamp(value: datetime | float | None) -> str:
    from sase.core.time import get_timezone

    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    return datetime.now(get_timezone()).isoformat()
