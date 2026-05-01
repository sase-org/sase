"""Maintenance marker for temporarily quiescing axe lumberjacks."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.time import get_timezone

from . import state as axe_state

MAINTENANCE_FILENAME = "maintenance.json"
DEFAULT_STALE_SECONDS = 24 * 60 * 60


def _maintenance_path() -> Path:
    return axe_state.AXE_STATE_DIR / MAINTENANCE_FILENAME


def _now_iso() -> str:
    return datetime.now(get_timezone()).isoformat()


def _parse_started_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed


def start_maintenance(reason: str) -> dict[str, Any]:
    """Create the axe maintenance marker and return its payload."""
    marker = {
        "reason": reason,
        "pid": os.getpid(),
        "started_at": _now_iso(),
    }
    axe_state._atomic_write_json(_maintenance_path(), marker)
    return marker


def read_maintenance() -> dict[str, Any] | None:
    """Read the active maintenance marker, if present and well-formed."""
    marker = axe_state._read_json(_maintenance_path())
    if not isinstance(marker, dict):
        return None
    reason = marker.get("reason")
    pid = marker.get("pid")
    started_at = marker.get("started_at")
    if not isinstance(reason, str) or not reason:
        return None
    if not isinstance(pid, int):
        return None
    if _parse_started_at(started_at) is None:
        return None
    return dict(marker)


def clear_maintenance() -> bool:
    """Remove the maintenance marker.

    Returns:
        True if a marker was removed, False if none was present.
    """
    path = _maintenance_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def clear_stale_maintenance(
    max_age_seconds: int = DEFAULT_STALE_SECONDS,
) -> dict[str, Any] | None:
    """Clear and return an old marker or one whose owner PID has exited."""
    raw_marker = axe_state._read_json(_maintenance_path())
    if not isinstance(raw_marker, dict):
        return None
    marker = dict(raw_marker)

    started_at = _parse_started_at(marker.get("started_at"))
    if started_at is None:
        clear_maintenance()
        return marker

    max_age = timedelta(seconds=max_age_seconds)
    if datetime.now(get_timezone()) - started_at > max_age:
        clear_maintenance()
        return marker

    pid = marker.get("pid")
    if isinstance(pid, int) and pid > 0 and not is_process_running(pid):
        clear_maintenance()
        return marker
    return None


@contextmanager
def enter_maintenance(reason: str) -> Iterator[dict[str, Any]]:
    """Context manager that creates and clears an axe maintenance marker."""
    marker = start_maintenance(reason)
    try:
        yield marker
    finally:
        clear_maintenance()
