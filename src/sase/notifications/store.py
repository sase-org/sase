"""JSONL-backed notification storage with file locking."""

import dataclasses
import fcntl
import json
import os
from datetime import datetime
from pathlib import Path

from sase.notifications.models import Notification

NOTIFICATIONS_DIR = os.path.expanduser("~/.sase/notifications")
NOTIFICATIONS_FILE = os.path.join(NOTIFICATIONS_DIR, "notifications.jsonl")


def _notification_from_dict(data: dict) -> Notification | None:
    """Safely construct a Notification from a dict, returning None on invalid data."""
    try:
        return Notification(
            id=data["id"],
            timestamp=data["timestamp"],
            sender=data["sender"],
            notes=data.get("notes", []),
            files=data.get("files", []),
            action=data.get("action"),
            action_data=data.get("action_data", {}),
            read=data.get("read", False),
            dismissed=data.get("dismissed", False),
            silent=data.get("silent", False),
            muted=data.get("muted", False),
            snooze_until=data.get("snooze_until"),
        )
    except (KeyError, TypeError):
        return None


def append_notification(n: Notification) -> None:
    """Append a notification as a JSON line with exclusive file locking."""
    os.makedirs(NOTIFICATIONS_DIR, exist_ok=True)
    with open(NOTIFICATIONS_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(dataclasses.asdict(n)) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load_notifications(include_dismissed: bool = False) -> list[Notification]:
    """Load notifications from the JSONL file with shared locking.

    Skips invalid lines silently.
    """
    path = Path(NOTIFICATIONS_FILE)
    if not path.exists():
        return []

    with open(path) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            lines = f.readlines()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    notifications: list[Notification] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        n = _notification_from_dict(data)
        if n is None:
            continue
        if not include_dismissed and n.dismissed:
            continue
        notifications.append(n)
    return notifications


def _rewrite_notifications(notifications: list[Notification]) -> None:
    """Rewrite the entire notifications file with exclusive locking."""
    os.makedirs(NOTIFICATIONS_DIR, exist_ok=True)
    with open(NOTIFICATIONS_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for n in notifications:
                f.write(json.dumps(dataclasses.asdict(n)) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def rewrite_notifications(notifications: list[Notification]) -> None:
    """Rewrite the entire notifications file with exclusive locking."""
    _rewrite_notifications(notifications)


def mark_read(notification_id: str) -> bool:
    """Mark a notification as read. Returns True if found."""
    all_notifications = load_notifications(include_dismissed=True)
    found = False
    for n in all_notifications:
        if n.id == notification_id:
            n.read = True
            found = True
            break
    if found:
        _rewrite_notifications(all_notifications)
    return found


def mark_dismissed(notification_id: str) -> bool:
    """Mark a notification as dismissed. Returns True if found."""
    all_notifications = load_notifications(include_dismissed=True)
    found = False
    for n in all_notifications:
        if n.id == notification_id:
            n.dismissed = True
            found = True
            break
    if found:
        _rewrite_notifications(all_notifications)
    return found


def mark_muted(notification_id: str, muted: bool = True) -> bool:
    """Set the muted state of a notification. Returns True if found.

    Unmuting (``muted=False``) also clears any pending ``snooze_until`` —
    snooze is mute-with-a-timer, so unmuting cancels the timer.
    """
    all_notifications = load_notifications(include_dismissed=True)
    found = False
    for n in all_notifications:
        if n.id == notification_id:
            n.muted = muted
            if not muted:
                n.snooze_until = None
            found = True
            break
    if found:
        _rewrite_notifications(all_notifications)
    return found


def mark_snoozed(notification_id: str, until: datetime) -> bool:
    """Snooze a notification until ``until``. Returns True if found.

    Snooze is implemented as ``muted=True`` plus a ``snooze_until`` ISO
    timestamp; the next expiry pass flips it back to ``muted=False`` and
    clears the timer.
    """
    all_notifications = load_notifications(include_dismissed=True)
    found = False
    for n in all_notifications:
        if n.id == notification_id:
            n.muted = True
            n.snooze_until = until.isoformat()
            found = True
            break
    if found:
        _rewrite_notifications(all_notifications)
    return found


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

    expired_ids = {n.id for n in expired}
    all_notifications = load_notifications(include_dismissed=True)
    for n in all_notifications:
        if n.id in expired_ids:
            n.muted = False
            n.snooze_until = None
    _rewrite_notifications(all_notifications)
    return expired


def mark_all_read() -> int:
    """Mark all unread notifications as read. Returns count of newly marked."""
    all_notifications = load_notifications(include_dismissed=True)
    count = 0
    for n in all_notifications:
        if not n.read:
            n.read = True
            count += 1
    if count > 0:
        _rewrite_notifications(all_notifications)
    return count
