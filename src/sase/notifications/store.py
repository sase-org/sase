"""Rust-backed JSONL notification storage."""

import dataclasses
import logging
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.notifications.models import Notification

log = logging.getLogger(__name__)

NOTIFICATIONS_DIR = os.path.expanduser("~/.sase/notifications")
NOTIFICATIONS_FILE = os.path.join(NOTIFICATIONS_DIR, "notifications.jsonl")


# Process-local cache of the parsed notifications file. Keyed by a
# (size, mtime_ns, inode, include_dismissed) tuple so cross-process writes
# (e.g. a Telegram callback updating a notification) invalidate naturally
# via the stat() check; in-process writes invalidate explicitly.
_LOAD_CACHE: dict[tuple[int, int, int, bool], list[Notification]] = {}


def _invalidate_load_cache() -> None:
    """Drop the cached parse — call after any in-process write."""
    _LOAD_CACHE.clear()


def _notifications_path() -> Path:
    return Path(NOTIFICATIONS_FILE)


def _ensure_notifications_dir() -> None:
    os.makedirs(NOTIFICATIONS_DIR, exist_ok=True)


def _clone_notifications(notifications: list[Notification]) -> list[Notification]:
    return [dataclasses.replace(n) for n in notifications]


def _rust_append_notification(path: Path, notification: Notification) -> Any:
    from sase.core import notification_store_facade

    return notification_store_facade.append_notification(path, notification)


def _rust_apply_notification_state_update(path: Path, update: Any) -> Any:
    from sase.core import notification_store_facade

    return notification_store_facade.apply_notification_state_update(path, update)


def _rust_read_notifications_snapshot(
    path: Path,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
) -> Any:
    from sase.core import notification_store_facade

    return notification_store_facade.read_notifications_snapshot(
        path, include_dismissed, expire_due_snoozes
    )


def _rust_rewrite_notifications(path: Path, notifications: list[Notification]) -> Any:
    from sase.core.notification_store_facade import rewrite_notifications

    return rewrite_notifications(path, notifications)


def _state_update(**kwargs: Any) -> Any:
    from sase.core import notification_store_wire

    return notification_store_wire.NotificationStateUpdateWire(**kwargs)


def _agent_key(cl_name: str, raw_suffix: str | None = None) -> Any:
    from sase.core import notification_store_wire

    return notification_store_wire.NotificationAgentKeyWire(
        cl_name=cl_name, raw_suffix=raw_suffix
    )


def _apply_state_update(update: Any) -> Any:
    outcome = _rust_apply_notification_state_update(_notifications_path(), update)
    if outcome.rewritten or outcome.changed_count > 0:
        _invalidate_load_cache()
    return outcome


def append_notification(n: Notification) -> None:
    """Append a notification as a JSON line through the Rust store."""
    _ensure_notifications_dir()
    _rust_append_notification(_notifications_path(), n)
    try:
        from sase.notifications.pending_actions import register_notification

        register_notification(n)
    except Exception:
        log.warning("Failed to register pending notification action", exc_info=True)
    _invalidate_load_cache()


def load_notifications(include_dismissed: bool = False) -> list[Notification]:
    """Load notifications from the JSONL file with shared locking.

    Skips invalid lines silently. Results are cached per-process and keyed
    by file (size, mtime_ns, inode); cross-process writes invalidate the
    cache via the stat check, in-process writes invalidate explicitly.
    Returned ``Notification`` instances are fresh copies, so callers may
    mutate top-level fields without corrupting the cache.
    """
    path = Path(NOTIFICATIONS_FILE)
    try:
        st = path.stat()
    except FileNotFoundError:
        return []

    key = (st.st_size, st.st_mtime_ns, st.st_ino, include_dismissed)
    cached = _LOAD_CACHE.get(key)
    if cached is not None:
        return [dataclasses.replace(n) for n in cached]

    snapshot = _rust_read_notifications_snapshot(path, include_dismissed)
    notifications = snapshot.notifications

    # Drop any prior entries — only the latest stat is interesting and
    # this keeps the cache size bounded across long-running processes.
    _LOAD_CACHE.clear()
    _LOAD_CACHE[key] = _clone_notifications(notifications)
    return _clone_notifications(notifications)


def read_notification_snapshot(
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
) -> Any:
    """Read a Rust-backed notification snapshot for count-sensitive callers."""
    snapshot = _rust_read_notifications_snapshot(
        _notifications_path(), include_dismissed, expire_due_snoozes
    )
    if snapshot.expired_ids:
        _invalidate_load_cache()
    return snapshot


def rewrite_notifications(notifications: list[Notification]) -> None:
    """Rewrite the entire notifications file through the Rust store."""
    _ensure_notifications_dir()
    _rust_rewrite_notifications(_notifications_path(), notifications)
    _invalidate_load_cache()


def mark_read(notification_id: str) -> bool:
    """Mark a notification as read. Returns True if found."""
    outcome = _apply_state_update(_state_update(kind="mark_read", id=notification_id))
    return outcome.matched_count > 0


def mark_dismissed(notification_id: str) -> bool:
    """Mark a notification as dismissed. Returns True if found."""
    outcome = _apply_state_update(
        _state_update(kind="mark_dismissed", id=notification_id)
    )
    return outcome.matched_count > 0


def mark_many_dismissed(notification_ids: Iterable[str]) -> int:
    """Mark notifications as dismissed. Returns the number of found rows."""
    ids = tuple(notification_ids)
    if not ids:
        return 0
    outcome = _apply_state_update(_state_update(kind="mark_many_dismissed", ids=ids))
    return int(outcome.matched_count)


def mark_muted(notification_id: str, muted: bool = True) -> bool:
    """Set the muted state of a notification. Returns True if found.

    Unmuting (``muted=False``) also clears any pending ``snooze_until`` —
    snooze is mute-with-a-timer, so unmuting cancels the timer.
    """
    outcome = _apply_state_update(
        _state_update(kind="mark_muted", id=notification_id, muted=muted)
    )
    return outcome.matched_count > 0


def mark_snoozed(notification_id: str, until: datetime) -> bool:
    """Snooze a notification until ``until``. Returns True if found.

    Snooze is implemented as ``muted=True`` plus a ``snooze_until`` ISO
    timestamp; the next expiry pass flips it back to ``muted=False`` and
    clears the timer.
    """
    outcome = _apply_state_update(
        _state_update(kind="mark_snoozed", id=notification_id, until=until.isoformat())
    )
    return outcome.matched_count > 0


def expire_due_snoozes(notifications: list[Notification]) -> list[Notification]:
    """Flip any snoozed notifications whose deadline has passed.

    Walks ``notifications`` (which the caller already loaded), finds rows
    where ``snooze_until`` is set and at or before now, and sets
    ``muted=False`` and ``snooze_until=None`` on them — both in-memory
    and on disk via a single rewrite. Returns the list of rows that just
    expired (empty if none).
    """
    from sase.core.time import get_timezone

    now = datetime.now(get_timezone())
    expired: list[Notification] = []
    for n in notifications:
        if not n.snooze_until:
            continue
        try:
            deadline = datetime.fromisoformat(n.snooze_until)
        except ValueError:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=get_timezone())
        if deadline <= now:
            n.muted = False
            n.snooze_until = None
            expired.append(n)

    if not expired:
        return expired

    outcome = _apply_state_update(
        _state_update(kind="expire_snoozes", now=now.isoformat())
    )
    expired_ids = set(outcome.expired_ids)
    if not expired_ids:
        return []

    rows_by_id = {n.id: n for n in outcome.notifications}
    expired = []
    for n in notifications:
        if n.id not in expired_ids:
            continue
        updated = rows_by_id.get(n.id)
        n.muted = updated.muted if updated is not None else False
        n.snooze_until = updated.snooze_until if updated is not None else None
        expired.append(n)
    return expired


def mark_all_read() -> int:
    """Mark all unread notifications as read. Returns count of newly marked."""
    outcome = _apply_state_update(_state_update(kind="mark_all_read"))
    return int(outcome.changed_count)


def _agent_key_from_mapping(data: dict[str, Any]) -> Any | None:
    cl_name = data.get("cl_name")
    if not cl_name:
        return None
    raw_suffix = data.get("raw_suffix")
    return _agent_key(
        cl_name=str(cl_name),
        raw_suffix=None if raw_suffix is None else str(raw_suffix),
    )


def dismiss_notifications_matching_agents(
    agent_keys: list[dict[str, Any] | Any],
) -> int:
    """Dismiss unread notifications that reference any supplied agent key."""
    from sase.core import notification_store_wire

    keys: list[Any] = []
    for item in agent_keys:
        if isinstance(item, notification_store_wire.NotificationAgentKeyWire):
            keys.append(item)
            continue
        key = _agent_key_from_mapping(item)
        if key is not None:
            keys.append(key)

    if not keys:
        return 0

    outcome = _apply_state_update(
        _state_update(
            kind="dismiss_matching_agents",
            agents=tuple(keys),
        )
    )
    return int(outcome.changed_count)
