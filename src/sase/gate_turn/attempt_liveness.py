"""Small helpers for checking persisted gate follow-up attempt liveness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ATTEMPT_LIVE_FIELD = "gate_followup_attempt_live"
ATTEMPT_OWNER_PID_FIELD = "gate_followup_attempt_owner_pid"


def gate_followup_attempt_is_live(meta: Mapping[str, Any]) -> bool:
    """Return whether the recorded follow-up attempt still has a live owner."""
    if not bool(meta.get(ATTEMPT_LIVE_FIELD)):
        return False
    owner_pid = _optional_int(meta.get(ATTEMPT_OWNER_PID_FIELD))
    if owner_pid is None:
        return True

    from sase.ace.hooks.processes import is_process_running

    return is_process_running(owner_pid)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ATTEMPT_LIVE_FIELD",
    "ATTEMPT_OWNER_PID_FIELD",
    "gate_followup_attempt_is_live",
]
