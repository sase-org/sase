"""TUI user-activity timestamp tracking.

Writes and reads a timestamp file so external chop scripts can detect
user inactivity and send notifications (e.g. via Telegram).
"""

from __future__ import annotations

import os
from pathlib import Path

ACTIVITY_FILE: Path = Path.home() / ".sase" / "tui_last_activity"
PID_FILE: Path = Path.home() / ".sase" / "tui_pid"


def write_activity_timestamp(epoch: float) -> None:
    """Atomically write *epoch* to the activity file.

    Creates parent directories if they don't exist.  Uses a temporary
    file + ``os.replace()`` so readers never see a partial write.
    """
    ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVITY_FILE.with_suffix(".tmp")
    tmp.write_text(str(epoch))
    os.replace(tmp, ACTIVITY_FILE)


# pyvision: public_api_methods.txt
def get_tui_last_activity() -> float | None:
    """Return the epoch stored in the activity file, or ``None``."""
    try:
        return float(ACTIVITY_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_tui_pid() -> None:
    """Write the current process PID to the PID file.

    Uses a temporary file + ``os.replace()`` so readers never see a partial write.
    """
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PID_FILE.with_suffix(".tmp")
    tmp.write_text(str(os.getpid()))
    os.replace(tmp, PID_FILE)


def remove_tui_pid() -> None:
    """Delete the PID file, ignoring if it doesn't exist."""
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


# pyvision: public_api_methods.txt
def is_tui_running() -> bool:
    """Return whether the TUI process is currently alive.

    Reads the PID from the PID file and probes it with ``os.kill(pid, 0)``.
    Returns ``False`` if the file is missing, contains invalid data, or the
    process is dead.  Cleans up stale PID files.
    """
    try:
        pid = int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # Process is dead — clean up stale PID file
        PID_FILE.unlink(missing_ok=True)
        return False
    except PermissionError:
        # Process exists but owned by a different user
        return True
    return True


# pyvision: public_api_methods.txt
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


# pyvision: public_api_methods.txt
def is_idle() -> bool:
    """Return True if the user is idle.

    The user is considered idle when:
    - The TUI is not running, OR
    - The IDLE indicator is (or would be) shown in the TUI
      (inactivity >= configured ``ace.inactive_seconds`` threshold,
       or user manually marked inactive via the I key).
    """
    if not is_tui_running():
        return True
    inactive = get_tui_inactive_seconds()
    if inactive is None:
        return True
    return inactive >= _get_idle_threshold()


def _get_idle_threshold() -> int:
    """Return the idle threshold in seconds from sase config.

    Reads ``ace.inactive_seconds`` from the merged config, defaulting to 600.
    """
    try:
        from sase.config import load_merged_config

        cfg = load_merged_config()
        ace_cfg = cfg.get("ace", {})
        if isinstance(ace_cfg, dict) and "inactive_seconds" in ace_cfg:
            return int(ace_cfg["inactive_seconds"])
    except Exception:
        pass
    return 600
