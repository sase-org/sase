"""TUI user-activity timestamp tracking.

Writes and reads a timestamp file so external chop scripts can detect
user inactivity and send notifications (e.g. via Telegram).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

ACTIVITY_FILE: Path = Path.home() / ".sase" / "tui_last_activity"
PID_FILE: Path = Path.home() / ".sase" / "tui_pid"
IDLE_STATE_FILE: Path = Path.home() / ".sase" / "tui_idle_state"
LAST_KEYPRESS_FILE: Path = Path.home() / ".sase" / "tui_last_keypress"
PINNED_IDLE_FILE: Path = Path.home() / ".sase" / "tui_pinned_idle"

# If the TUI is running and reports idle, but the last keypress was
# less than this many seconds ago, something is wrong — override
# the idle state and return False.  120s is well below any reasonable
# inactive_seconds threshold (default 600s).
_IDLE_GUARD_SECONDS = 120

# Shorter guard for the "idle_state=0 but PID file missing" case.
# Here we're only trying to cover brief PID file gaps during TUI
# restarts (typically < 5s), not the full idle transition window.
# 30s is generous enough for restarts but short enough to avoid
# blocking legitimate notifications after the user goes idle.
_PID_MISSING_GUARD_SECONDS = 30


def write_activity_timestamp(epoch: float) -> None:
    """Atomically write *epoch* to the activity file.

    Creates parent directories if they don't exist.  Uses a temporary
    file + ``os.replace()`` so readers never see a partial write.
    """
    ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVITY_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(str(epoch))
    os.replace(tmp, ACTIVITY_FILE)


def write_last_keypress(epoch: float) -> None:
    """Atomically write the last keypress wall-clock time.

    Unlike ``write_activity_timestamp``, this is NEVER overwritten on
    idle transitions.  It always reflects the actual wall-clock time of
    the most recent user keypress, allowing ``is_idle()`` to
    independently verify that enough time has elapsed.
    """
    LAST_KEYPRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAST_KEYPRESS_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(str(epoch))
    os.replace(tmp, LAST_KEYPRESS_FILE)


def get_last_keypress() -> float | None:
    """Return the epoch stored in the last-keypress file, or ``None``."""
    try:
        return float(LAST_KEYPRESS_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


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
    tmp = PID_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
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
    tmp = IDLE_STATE_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("1" if idle else "0")
    os.replace(tmp, IDLE_STATE_FILE)


def remove_idle_state() -> None:
    """Delete the idle-state file, ignoring if it doesn't exist."""
    try:
        IDLE_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def remove_last_keypress() -> None:
    """Delete the last-keypress file, ignoring if it doesn't exist."""
    try:
        LAST_KEYPRESS_FILE.unlink()
    except FileNotFoundError:
        pass


def write_pinned_idle(pinned: bool) -> None:
    """Atomically write the pinned idle state to disk.

    Persists the pinned idle flag so the TUI can restore it after a restart.
    """
    PINNED_IDLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PINNED_IDLE_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("1" if pinned else "0")
    os.replace(tmp, PINNED_IDLE_FILE)


def read_pinned_idle() -> bool:
    """Return whether pinned idle was active in a previous session."""
    try:
        return PINNED_IDLE_FILE.read_text().strip() == "1"
    except (FileNotFoundError, ValueError):
        return False


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


def is_idle() -> bool:
    """Return True if the user is idle.

    Reads the authoritative idle state written by the TUI process.
    The TUI is the single source of truth — it writes the state file
    whenever its idle indicator changes, so external consumers never
    need to independently recompute idle from raw timestamps.

    The idle state file is the primary signal.  The PID file and
    last-keypress file serve as secondary checks:

    - When idle_state says "not idle" but the PID file is missing,
      a recent keypress corroborates that the TUI is still alive
      (guards against a missing PID file, which can happen due to
      races during TUI restarts or external cleanup).
    - When idle_state says "idle", a recent keypress overrides the
      state file (catches races and stale state).

    Falls back to True (idle) when the state file is missing or
    unreadable, or when the TUI appears to have crashed (state says
    active but no PID and no recent keypress).
    """
    try:
        idle_flag = IDLE_STATE_FILE.read_text().strip() == "1"
    except (FileNotFoundError, ValueError):
        return True

    tui_running = _is_tui_running()

    if not idle_flag:
        # TUI says user is active.  Trust it if the TUI process is
        # confirmed alive.
        if tui_running:
            return False
        # PID file is missing.  Use a SHORT keypress guard to cover
        # brief PID file gaps during TUI restarts, but don't block
        # notifications for an extended period — the PID file is
        # chronically missing in practice, so a long guard window
        # (like _IDLE_GUARD_SECONDS) would suppress legitimate sends.
        if _has_recent_keypress(_PID_MISSING_GUARD_SECONDS):
            return False
        # No PID and no recent keypress — stale state from a crashed TUI.
        return True

    # idle_state says idle.
    if not tui_running:
        return True
    # When the user manually marked idle (activity epoch == 0), trust
    # their explicit intent — skip the keypress safety guard.
    activity_ts = get_tui_last_activity()
    if activity_ts is not None and activity_ts == 0:
        return True
    # Safety guard: recent keypress overrides the idle state file.
    if _has_recent_keypress():
        return False
    return True


def _has_recent_keypress(threshold: float = _IDLE_GUARD_SECONDS) -> bool:
    """Return True if a keypress occurred within *threshold* seconds."""
    last_kp = get_last_keypress()
    if last_kp is not None and last_kp > 0:
        return time.time() - last_kp < threshold
    return False
