"""TUI user-activity timestamp tracking.

Writes and reads a timestamp file so external chop scripts can detect
user inactivity and send notifications (e.g. via Telegram).
"""

from __future__ import annotations

import os
from pathlib import Path

ACTIVITY_FILE: Path = Path.home() / ".sase" / "tui_last_activity"


def write_activity_timestamp(epoch: float) -> None:
    """Atomically write *epoch* to the activity file.

    Creates parent directories if they don't exist.  Uses a temporary
    file + ``os.replace()`` so readers never see a partial write.
    """
    ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVITY_FILE.with_suffix(".tmp")
    tmp.write_text(str(epoch))
    os.replace(tmp, ACTIVITY_FILE)


def get_tui_last_activity() -> float | None:
    """Return the epoch stored in the activity file, or ``None``."""
    try:
        return float(ACTIVITY_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def get_tui_inactive_seconds() -> float | None:
    """Return seconds since the last recorded TUI activity.

    Returns ``float('inf')`` when the epoch is 0 (user manually marked
    inactive).  Returns ``None`` if the activity file is missing or
    unreadable.
    """
    import time

    epoch = get_tui_last_activity()
    if epoch is None:
        return None
    if epoch == 0:
        return float("inf")
    return time.time() - epoch
