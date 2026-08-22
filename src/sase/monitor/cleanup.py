"""Execute planner monitor-stop intents through the canonical stop path."""

from __future__ import annotations

from typing import Any


class _MonitorStopError(RuntimeError):
    """A requested monitor-stop intent could not leave the running state."""


def execute_monitor_stop_intents(cleanup_plan: object) -> None:
    """Stop every monitor named by the plan before other cleanup side effects.

    Already-terminal or missing monitors are idempotent successes. A monitor
    that remains ``running`` after the canonical stop fails the transaction.
    """
    side_effects = getattr(cleanup_plan, "side_effects", None)
    intents = tuple(getattr(side_effects, "monitor_stop_requests", ()) or ())
    if not intents:
        return

    from sase.monitor.models import MonitorRefError
    from sase.monitor.store import (
        list_monitors,
        read_monitor_marker,
        resolve_monitor_ref,
        stop_monitor,
    )

    records = list_monitors()
    by_id = {record.monitor_id: record for record in records}
    for intent in intents:
        monitor_id = str(getattr(intent, "monitor_id", "") or "")
        if not monitor_id:
            raise _MonitorStopError(
                "cleanup plan requested a monitor stop without an id"
            )
        record = by_id.get(monitor_id)
        if record is None:
            try:
                record = resolve_monitor_ref(monitor_id, records)
            except (MonitorRefError, ValueError):
                continue
        if record.monitor_state != "running":
            continue
        result = stop_monitor(record)
        current = read_monitor_marker(result.project_name, result.artifacts_dir)
        settled = current if current is not None else result
        if settled.monitor_state == "running":
            raise _MonitorStopError(f"Monitor {monitor_id} remained running after stop")


def owned_live_monitors_for_name(name: str) -> list[Any]:
    """Return running monitors addressed by *name* as a member, lane, or id."""
    from sase.monitor.models import MonitorRefError
    from sase.monitor.store import list_monitors, resolve_monitor_ref

    records = list_monitors()
    try:
        resolved = resolve_monitor_ref(name, records)
    except (MonitorRefError, ValueError):
        return []
    if resolved.monitor_state != "running":
        return []
    return [resolved]


__all__ = [
    "execute_monitor_stop_intents",
    "owned_live_monitors_for_name",
]
