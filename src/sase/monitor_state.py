"""Monitor state semantics shared by monitor storage and projections."""

from __future__ import annotations

MONITOR_STATE_BUCKETS: dict[str, str] = {
    "running": "Running",
    "completed": "Done",
    "failed": "Failed",
    "timeout": "Failed",
    "stopped": "Done",
}


def monitor_state_bucket(monitor_state: str | None) -> str:
    """Return the status bucket for a monitor's ``monitor_state``.

    An unrecognized or missing state buckets as ``Running`` so a monitor
    member that has not (yet) reached a terminal state never reads as
    finished.
    """
    return MONITOR_STATE_BUCKETS.get(monitor_state or "", "Running")


__all__ = ["MONITOR_STATE_BUCKETS", "monitor_state_bucket"]
