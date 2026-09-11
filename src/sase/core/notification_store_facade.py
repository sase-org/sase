"""Python facade for the Rust notification-store bindings."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.notification_store_wire import (
    NotificationPlusOneOutcomeWire,
    NotificationPlusOneRequestWire,
    NotificationStateUpdateWire,
    NotificationStoreSnapshotWire,
    NotificationTabClassificationWire,
    NotificationUpdateOutcomeWire,
    NotificationUpsertOutcomeWire,
    NotificationUpsertRequestWire,
    notification_plus_one_outcome_from_dict,
    notification_snapshot_from_dict,
    notification_store_wire_to_json_dict,
    notification_tab_classification_from_dict,
    notification_update_outcome_from_dict,
    notification_upsert_outcome_from_dict,
)
from sase.core.rust import require_rust_binding
from sase.notifications.models import Notification

# Process-local snapshot memo keyed by path, include_dismissed, and whether the
# read expires due snoozes. The change token is mtime_ns + size + inode so an
# unchanged live file is not re-parsed on the TUI refresh cadence.
_SNAPSHOT_CACHE_LOCK = threading.RLock()
_SNAPSHOT_CACHE: dict[
    tuple[str, bool, bool], tuple[tuple[Any, ...], NotificationStoreSnapshotWire]
] = {}
_SNAPSHOT_CACHE_GENERATION = 0


@dataclass(frozen=True)
class NotificationStoreCompactionOutcome:
    """Result of one housekeeping compaction pass over the live JSONL store."""

    live_exists: bool
    live_bytes_before: int
    live_bytes_after: int
    live_rows_after: int
    archived_count: int
    archive_path: str


def invalidate_notification_snapshot_cache() -> None:
    """Drop memoized snapshots. Call after any in-process store mutation."""
    global _SNAPSHOT_CACHE_GENERATION
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()
        _SNAPSHOT_CACHE_GENERATION += 1


def notification_archive_path(path: Path | str) -> Path:
    """Return the sibling archive path for a live notifications JSONL file."""
    live = _normalize_store_path(path)
    if live.suffix:
        return live.with_name(f"{live.stem}-archive{live.suffix}")
    return live.with_name(f"{live.name}-archive")


def read_notifications_snapshot(
    path: Path | str,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
) -> NotificationStoreSnapshotWire:
    """Read notification rows through ``sase_core_rs`` and rehydrate wires.

    Unchanged ``(path, include_dismissed, expire_due_snoozes)`` reads reuse a
    memoized snapshot keyed by the live file's mtime+size token. A due
    ``next_snooze_deadline`` still forces a re-read when ``expire_due_snoozes``
    is set.
    """
    return _read_snapshot_cached(path, include_dismissed, expire_due_snoozes)


def read_current_notifications_snapshot(
    path: Path | str,
    include_dismissed: bool = False,
) -> NotificationStoreSnapshotWire:
    """Read and atomically reconcile the user-facing current store state."""
    # Keep the Python package compatible with the published minimum core while
    # the named Rust binding rolls out; the option is a compatibility alias for
    # the same canonical core operation.
    return _read_snapshot_cached(path, include_dismissed, True)


def compact_notification_store(
    path: Path | str,
) -> NotificationStoreCompactionOutcome:
    """Archive eligible dismissed rows out of the live store.

    Bypasses the snapshot cache and calls the Rust reader with
    ``include_dismissed=True`` so compact-on-read runs under the store lock.
    Interactive paths must not call this; the hourly housekeeping lumberjack
    owns the pass.
    """
    live = _normalize_store_path(path)
    archive = notification_archive_path(live)
    live_exists = live.is_file()
    live_bytes_before = live.stat().st_size if live_exists else 0
    archived_before = _jsonl_row_count(archive)
    invalidate_notification_snapshot_cache()
    snapshot = _read_snapshot_from_rust(path, include_dismissed=True, expire=False)
    live_bytes_after = live.stat().st_size if live.is_file() else 0
    archived_after = _jsonl_row_count(archive)
    archived_count = max(0, archived_after - archived_before)
    invalidate_notification_snapshot_cache()
    return NotificationStoreCompactionOutcome(
        live_exists=live_exists,
        live_bytes_before=live_bytes_before,
        live_bytes_after=live_bytes_after,
        live_rows_after=int(snapshot.stats.loaded_rows),
        archived_count=archived_count,
        archive_path=str(archive),
    )


def classify_notification_tabs(
    notifications: list[Notification] | tuple[Notification, ...],
) -> NotificationTabClassificationWire:
    """Classify a page of notifications into ordered, single-owner tabs.

    One call classifies the whole page, so no caller pays an FFI hop per row.
    """
    binding = require_rust_binding("classify_notification_tabs")
    payload: dict[str, Any] = binding(
        notification_store_wire_to_json_dict(list(notifications))
    )
    return notification_tab_classification_from_dict(payload)


def apply_notification_state_update(
    path: Path | str,
    update: NotificationStateUpdateWire | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Apply one state update through Rust and return the typed outcome."""
    payload = _call_mutating_binding(
        "apply_notification_state_update",
        str(path),
        notification_store_wire_to_json_dict(update),
    )
    return notification_update_outcome_from_dict(payload)


def apply_notification_state_update_counts(
    path: Path | str,
    update: NotificationStateUpdateWire | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Apply one state update through Rust and return mutation metadata only."""
    payload = _call_mutating_binding(
        "apply_notification_state_update_counts",
        str(path),
        notification_store_wire_to_json_dict(update),
    )
    return notification_update_outcome_from_dict(payload)


def append_notification(
    path: Path | str,
    notification: Notification | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Append one notification through Rust and return the typed outcome."""
    payload = _call_mutating_binding(
        "append_notification",
        str(path),
        notification_store_wire_to_json_dict(notification),
    )
    return notification_update_outcome_from_dict(payload)


def append_notification_counts(
    path: Path | str,
    notification: Notification | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Append one notification through Rust and return mutation metadata only."""
    payload = _call_mutating_binding(
        "append_notification_counts",
        str(path),
        notification_store_wire_to_json_dict(notification),
    )
    return notification_update_outcome_from_dict(payload)


def rewrite_notifications(
    path: Path | str,
    notifications: list[Notification] | tuple[Notification, ...] | list[dict[str, Any]],
) -> NotificationUpdateOutcomeWire:
    """Rewrite the store through Rust's lock/tempfile/rename path."""
    payload = _call_mutating_binding(
        "rewrite_notifications",
        str(path),
        notification_store_wire_to_json_dict(notifications),
    )
    return notification_update_outcome_from_dict(payload)


def rewrite_notifications_counts(
    path: Path | str,
    notifications: list[Notification] | tuple[Notification, ...] | list[dict[str, Any]],
) -> NotificationUpdateOutcomeWire:
    """Rewrite the store through Rust and return mutation metadata only."""
    payload = _call_mutating_binding(
        "rewrite_notifications_counts",
        str(path),
        notification_store_wire_to_json_dict(notifications),
    )
    return notification_update_outcome_from_dict(payload)


def append_notification_plus_one(
    path: Path | str,
    request: NotificationPlusOneRequestWire | dict[str, Any],
) -> NotificationPlusOneOutcomeWire:
    """Append one +1, addressed by id or ``(sender, dedup_key)``, through Rust."""
    payload = _call_mutating_binding(
        "append_notification_plus_one",
        str(path),
        notification_store_wire_to_json_dict(request),
    )
    return notification_plus_one_outcome_from_dict(payload)


def upsert_notification(
    path: Path | str,
    request: NotificationUpsertRequestWire | dict[str, Any],
) -> NotificationUpsertOutcomeWire:
    """Create a minted row, or +1 the matching ``dedup_key`` row, through Rust."""
    payload = _call_mutating_binding(
        "upsert_notification",
        str(path),
        notification_store_wire_to_json_dict(request),
    )
    return notification_upsert_outcome_from_dict(payload)


def _normalize_store_path(path: Path | str) -> Path:
    live = Path(path).expanduser()
    try:
        return live.resolve()
    except OSError:
        return live.absolute()


def _change_token(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
    except OSError:
        return ("missing",)
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def _clone_notification(notification: Notification) -> Notification:
    return replace(
        notification,
        notes=list(notification.notes),
        files=list(notification.files),
        tags=list(notification.tags),
        action_data=dict(notification.action_data),
        plus_ones=list(notification.plus_ones),
    )


def _clone_snapshot(
    snapshot: NotificationStoreSnapshotWire,
) -> NotificationStoreSnapshotWire:
    return replace(
        snapshot,
        notifications=[_clone_notification(row) for row in snapshot.notifications],
        tabs=list(snapshot.tabs),
        expired_ids=list(snapshot.expired_ids),
    )


def _snooze_deadline_is_due(deadline: str | None) -> bool:
    if deadline is None:
        return False
    try:
        parsed = datetime.fromisoformat(deadline)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)


def _read_snapshot_from_rust(
    path: Path | str,
    include_dismissed: bool,
    expire: bool,
) -> NotificationStoreSnapshotWire:
    binding = require_rust_binding("read_notifications_snapshot")
    payload: dict[str, Any] = binding(str(path), include_dismissed, expire)
    return notification_snapshot_from_dict(payload)


def _read_snapshot_cached(
    path: Path | str,
    include_dismissed: bool,
    expire: bool,
) -> NotificationStoreSnapshotWire:
    live = _normalize_store_path(path)
    key = (str(live), include_dismissed, expire)
    token = _change_token(live)
    with _SNAPSHOT_CACHE_LOCK:
        generation = _SNAPSHOT_CACHE_GENERATION
        cached = _SNAPSHOT_CACHE.get(key)
        if cached is not None and cached[0] == token:
            snapshot = cached[1]
            if not (expire and _snooze_deadline_is_due(snapshot.next_snooze_deadline)):
                return _clone_snapshot(snapshot)

    snapshot = _read_snapshot_from_rust(path, include_dismissed, expire)
    memo = replace(snapshot, expired_ids=[])
    new_token = _change_token(live)
    with _SNAPSHOT_CACHE_LOCK:
        if generation == _SNAPSHOT_CACHE_GENERATION:
            _SNAPSHOT_CACHE[key] = (new_token, _clone_snapshot(memo))
    return snapshot


def _call_mutating_binding(name: str, *args: Any) -> dict[str, Any]:
    binding = require_rust_binding(name)
    try:
        payload: dict[str, Any] = binding(*args)
        return payload
    finally:
        invalidate_notification_snapshot_cache()


def _jsonl_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    with path.open("rb") as handle:
        for raw in handle:
            if raw.strip():
                count += 1
    return count


__all__ = [
    "NotificationStateUpdateWire",
    "NotificationStoreCompactionOutcome",
    "NotificationStoreSnapshotWire",
    "NotificationTabClassificationWire",
    "NotificationUpdateOutcomeWire",
    "append_notification",
    "append_notification_counts",
    "append_notification_plus_one",
    "apply_notification_state_update",
    "apply_notification_state_update_counts",
    "classify_notification_tabs",
    "compact_notification_store",
    "invalidate_notification_snapshot_cache",
    "notification_archive_path",
    "read_current_notifications_snapshot",
    "read_notifications_snapshot",
    "rewrite_notifications",
    "rewrite_notifications_counts",
    "upsert_notification",
]
