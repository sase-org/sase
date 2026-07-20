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
_PROC_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def _maintenance_path() -> Path:
    return axe_state.axe_state_dir() / MAINTENANCE_FILENAME


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
    marker: dict[str, Any] = {
        "reason": reason,
        "pid": os.getpid(),
        "started_at": _now_iso(),
    }
    owner_identity = _process_identity(marker["pid"])
    if owner_identity is not None:
        marker["owner_identity"] = owner_identity
    axe_state.atomic_write_json(_maintenance_path(), marker)
    return marker


def read_maintenance() -> dict[str, Any] | None:
    """Read the active maintenance marker, if present and well-formed."""
    marker = axe_state.read_json(_maintenance_path())
    if not isinstance(marker, dict):
        return None
    reason = marker.get("reason")
    pid = marker.get("pid")
    started_at = marker.get("started_at")
    if not isinstance(reason, str) or not reason:
        return None
    if not isinstance(pid, int) or pid <= 0:
        return None
    if _parse_started_at(started_at) is None:
        return None
    if not _valid_owner_identity(marker.get("owner_identity")):
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
    """Clear and return an invalid marker or one whose owner is stale."""
    raw_marker = axe_state.read_json(_maintenance_path())
    if not isinstance(raw_marker, dict):
        if _maintenance_path().exists():
            clear_maintenance()
            return {"malformed": True}
        return None
    marker = dict(raw_marker)

    reason = marker.get("reason")
    pid = marker.get("pid")
    started_at = _parse_started_at(marker.get("started_at"))
    if (
        not isinstance(reason, str)
        or not reason
        or not isinstance(pid, int)
        or pid <= 0
        or started_at is None
        or not _valid_owner_identity(marker.get("owner_identity"))
    ):
        clear_maintenance()
        return marker

    max_age = timedelta(seconds=max_age_seconds)
    if datetime.now(get_timezone()) - started_at > max_age:
        clear_maintenance()
        return marker

    if not is_process_running(pid):
        clear_maintenance()
        return marker

    recorded_identity = marker.get("owner_identity")
    if isinstance(recorded_identity, dict):
        current_identity = _process_identity(pid)
        if current_identity is not None and not _same_process_identity(
            recorded_identity,
            current_identity,
        ):
            clear_maintenance()
            return marker
    return None


def _process_identity(pid: int) -> dict[str, Any] | None:
    """Return a Linux process identity that changes when a PID is recycled."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close_paren = stat.rfind(")")
        if close_paren < 0:
            return None
        # The tail starts at field 3 (state); process start time is field 22.
        fields = stat[close_paren + 1 :].split()
        start_ticks = int(fields[19])
    except (IndexError, OSError, ValueError):
        return None

    identity: dict[str, Any] = {"start_ticks": start_ticks}
    try:
        boot_id = _PROC_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = ""
    if boot_id:
        identity["boot_id"] = boot_id
    return identity


def _valid_owner_identity(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    start_ticks = value.get("start_ticks")
    if not isinstance(start_ticks, int) or start_ticks < 0:
        return False
    boot_id = value.get("boot_id")
    return boot_id is None or (isinstance(boot_id, str) and bool(boot_id))


def _same_process_identity(
    recorded: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    if recorded.get("start_ticks") != current.get("start_ticks"):
        return False
    recorded_boot_id = recorded.get("boot_id")
    current_boot_id = current.get("boot_id")
    if recorded_boot_id is not None and current_boot_id is not None:
        return recorded_boot_id == current_boot_id
    return True


@contextmanager
def _enter_maintenance(reason: str) -> Iterator[dict[str, Any]]:
    """Context manager that creates and clears an axe maintenance marker."""
    marker = start_maintenance(reason)
    try:
        yield marker
    finally:
        clear_maintenance()


_enter_maintenance_context = _enter_maintenance
