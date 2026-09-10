"""Host-wide runner-slot change signal.

Parked waiters back off while this token is unchanged and return to fast
polling when claim, release, or waiting-marker mutations bump it.
"""

from __future__ import annotations

import time
from pathlib import Path

from sase.core.paths import sase_home

_TOKEN_NAME = "runner_slots.token"


def _runner_slot_state_token_path() -> Path:
    """Return the host-wide slot-state token path under ``SASE_HOME``."""
    return sase_home() / _TOKEN_NAME


def runner_slot_state_token() -> str:
    """Return the current slot-state token, or empty when none has been written."""
    try:
        return _runner_slot_state_token_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def notify_runner_slot_state_changed() -> None:
    """Bump the slot-state token so parked waiters wake from backoff."""
    path = _runner_slot_state_token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time_ns()), encoding="utf-8")
    except OSError:
        return


__all__ = [
    "notify_runner_slot_state_changed",
    "runner_slot_state_token",
]
