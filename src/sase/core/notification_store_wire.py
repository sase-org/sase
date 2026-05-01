"""Wire records for the Rust notification-store facade."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sase.notifications.models import Notification

NOTIFICATION_STORE_WIRE_SCHEMA_VERSION = 1


# pyvision: tests/test_core_facade/test_notification_store.py
@dataclass(frozen=True)
class NotificationCountsWire:
    priority: int = 0
    rest: int = 0
    muted: int = 0


# pyvision: tests/test_core_facade/test_notification_store.py
@dataclass(frozen=True)
class NotificationStoreStatsWire:
    total_lines: int = 0
    blank_lines: int = 0
    invalid_json_lines: int = 0
    invalid_record_lines: int = 0
    loaded_rows: int = 0
    dismissed_filtered: int = 0


@dataclass(frozen=True)
class NotificationStoreSnapshotWire:
    schema_version: int
    notifications: list[Notification] = field(default_factory=list)
    counts: NotificationCountsWire = field(default_factory=NotificationCountsWire)
    expired_ids: list[str] = field(default_factory=list)
    stats: NotificationStoreStatsWire = field(
        default_factory=NotificationStoreStatsWire
    )


@dataclass(frozen=True)
class NotificationUpdateOutcomeWire:
    schema_version: int
    matched_count: int = 0
    changed_count: int = 0
    appended_count: int = 0
    rewritten: bool = False
    notifications: list[Notification] = field(default_factory=list)
    counts: NotificationCountsWire = field(default_factory=NotificationCountsWire)
    expired_ids: list[str] = field(default_factory=list)
    stats: NotificationStoreStatsWire = field(
        default_factory=NotificationStoreStatsWire
    )


# pyvision: tests/test_core_facade/test_notification_store.py
@dataclass(frozen=True)
class NotificationAgentKeyWire:
    cl_name: str
    raw_suffix: str | None = None


@dataclass(frozen=True)
class NotificationStateUpdateWire:
    """Tagged update record accepted by ``apply_notification_state_update``."""

    kind: str
    id: str | None = None
    ids: tuple[str, ...] = ()
    muted: bool | None = None
    until: str | None = None
    now: str | None = None
    agents: tuple[NotificationAgentKeyWire, ...] = ()
    notifications: tuple[Notification, ...] = ()


def notification_store_wire_to_json_dict(record: Any) -> Any:
    """Project notification wire records to the dict shape expected by Rust."""
    if isinstance(record, (list, tuple)):
        return [notification_store_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: notification_store_wire_to_json_dict(v) for k, v in record.items()}
    if isinstance(record, Notification):
        return asdict(record)
    if isinstance(record, NotificationStateUpdateWire):
        payload: dict[str, Any] = {"kind": record.kind}
        for key in ("id", "ids", "muted", "until", "now", "agents", "notifications"):
            value = getattr(record, key)
            if value is None or value == ():
                continue
            payload[key] = notification_store_wire_to_json_dict(value)
        return payload
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


# pyvision: tests/test_core_facade/test_notification_store.py
def notification_from_dict(data: dict[str, Any]) -> Notification:
    return Notification(
        id=str(data["id"]),
        timestamp=str(data["timestamp"]),
        sender=str(data["sender"]),
        notes=list(data.get("notes") or []),
        files=list(data.get("files") or []),
        action=None if data.get("action") is None else str(data["action"]),
        action_data={
            str(k): str(v) for k, v in (data.get("action_data") or {}).items()
        },
        read=bool(data.get("read", False)),
        dismissed=bool(data.get("dismissed", False)),
        silent=bool(data.get("silent", False)),
        muted=bool(data.get("muted", False)),
        snooze_until=(
            None if data.get("snooze_until") is None else str(data["snooze_until"])
        ),
    )


def notification_snapshot_from_dict(
    data: dict[str, Any],
) -> NotificationStoreSnapshotWire:
    schema = int(data["schema_version"])
    if schema != NOTIFICATION_STORE_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"notification store wire schema mismatch: got {schema}, "
            f"expected {NOTIFICATION_STORE_WIRE_SCHEMA_VERSION}"
        )
    return NotificationStoreSnapshotWire(
        schema_version=schema,
        notifications=[
            notification_from_dict(item) for item in data.get("notifications") or []
        ],
        counts=NotificationCountsWire(**(data.get("counts") or {})),
        expired_ids=[str(item) for item in data.get("expired_ids") or []],
        stats=NotificationStoreStatsWire(**(data.get("stats") or {})),
    )


def notification_update_outcome_from_dict(
    data: dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    schema = int(data["schema_version"])
    if schema != NOTIFICATION_STORE_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"notification store wire schema mismatch: got {schema}, "
            f"expected {NOTIFICATION_STORE_WIRE_SCHEMA_VERSION}"
        )
    return NotificationUpdateOutcomeWire(
        schema_version=schema,
        matched_count=int(data.get("matched_count", 0)),
        changed_count=int(data.get("changed_count", 0)),
        appended_count=int(data.get("appended_count", 0)),
        rewritten=bool(data.get("rewritten", False)),
        notifications=[
            notification_from_dict(item) for item in data.get("notifications") or []
        ],
        counts=NotificationCountsWire(**(data.get("counts") or {})),
        expired_ids=[str(item) for item in data.get("expired_ids") or []],
        stats=NotificationStoreStatsWire(**(data.get("stats") or {})),
    )


__all__ = [
    "NOTIFICATION_STORE_WIRE_SCHEMA_VERSION",
    "NotificationAgentKeyWire",
    "NotificationCountsWire",
    "NotificationStateUpdateWire",
    "NotificationStoreSnapshotWire",
    "NotificationStoreStatsWire",
    "NotificationUpdateOutcomeWire",
    "notification_from_dict",
    "notification_snapshot_from_dict",
    "notification_store_wire_to_json_dict",
    "notification_update_outcome_from_dict",
]
