"""TUI user-activity timestamp tracking.

Writes and reads a timestamp file so external chop scripts can detect
user inactivity and send notifications (e.g. via Telegram).
"""

from __future__ import annotations

import os
from pathlib import Path

ACTIVITY_FILE: Path = Path.home() / ".sase" / "tui_last_activity"
PID_FILE: Path = Path.home() / ".sase" / "tui_pid"
IDLE_STATE_FILE: Path = Path.home() / ".sase" / "tui_idle_state"


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


def write_idle_state(idle: bool) -> None:
    """Atomically write the TUI's idle state to disk.

    The TUI is the single authority on idle state.  External consumers
    (e.g. the Telegram outbound chop) read this file via ``is_idle()``
    instead of independently recomputing idle from raw timestamps.
    """
    IDLE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = IDLE_STATE_FILE.with_suffix(".tmp")
    tmp.write_text("1" if idle else "0")
    os.replace(tmp, IDLE_STATE_FILE)


def remove_idle_state() -> None:
    """Delete the idle-state file, ignoring if it doesn't exist."""
    try:
        IDLE_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def _is_tui_running() -> bool:
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
def is_idle() -> bool:
    """Return True if the user is idle.

    Reads the authoritative idle state written by the TUI process.
    The TUI is the single source of truth — it writes the state file
    whenever its idle indicator changes, so external consumers never
    need to independently recompute idle from raw timestamps.

    Falls back to True (idle) when the TUI is not running or the
    state file is missing/unreadable.
    """
    if not _is_tui_running():
        return True
    try:
        return IDLE_STATE_FILE.read_text().strip() == "1"
    except (FileNotFoundError, ValueError):
        return True
