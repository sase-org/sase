"""Derive the scheduler's desired state from the service host.

This replaces the retired ``~/.sase/axe/desired_state.json`` marker. The
service host is the scheduler's only supervisor, so its view of the
``scheduler`` service proc is the desired-state source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._status_records import AxeDesiredStateRecord

if TYPE_CHECKING:
    from sase.service.status import ServiceStatusProc

_DESIRED_STATE_SOURCE = "service host"
_SCHEDULER_PROC_NAME = "scheduler"


def scheduler_desired_state() -> AxeDesiredStateRecord | None:
    """Return the scheduler proc's desired state, or None when unknown."""
    proc, generated_at = _scheduler_proc()
    if proc is None:
        return None
    if proc.stop is not None:
        return AxeDesiredStateRecord(
            state="stopped",
            source=_DESIRED_STATE_SOURCE,
            timestamp=_iso_timestamp(proc.stop.stopped_at, fallback=generated_at),
        )
    if proc.desired == "running":
        return AxeDesiredStateRecord(
            state="running",
            source=_DESIRED_STATE_SOURCE,
            timestamp=_iso_timestamp(generated_at),
        )
    if proc.desired == "stopped":
        return AxeDesiredStateRecord(
            state="stopped",
            source=_DESIRED_STATE_SOURCE,
            timestamp=_iso_timestamp(generated_at),
        )
    return None


def scheduler_desired_running() -> bool:
    """Return True when the service host wants the scheduler running."""
    proc, _ = _scheduler_proc()
    if proc is None:
        return False
    return (
        bool(proc.enablement.enabled)
        and proc.desired == "running"
        and proc.stop is None
    )


def _scheduler_proc() -> tuple[ServiceStatusProc | None, float | None]:
    """Return the scheduler proc row plus its snapshot timestamp."""
    try:
        from sase.service.control import persisted_or_current_status

        snapshot = persisted_or_current_status()
    except Exception:  # noqa: BLE001 - unknown host state means unknown desire.
        return None, None
    for proc in (*snapshot.procs, *snapshot.orphans):
        if proc.name == _SCHEDULER_PROC_NAME:
            return proc, snapshot.generated_at
    return None, snapshot.generated_at


def _iso_timestamp(value: object, *, fallback: object = None) -> str:
    """Render an epoch timestamp as ISO, falling back to now on bad input."""
    for candidate in (value, fallback):
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            try:
                return datetime.fromtimestamp(candidate, UTC).isoformat()
            except (OverflowError, OSError, ValueError):
                continue
    return datetime.now(UTC).isoformat()


__all__ = [
    "scheduler_desired_running",
    "scheduler_desired_state",
]
