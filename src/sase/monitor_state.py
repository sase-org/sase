"""Monitor state semantics shared by monitor storage and projections."""

from __future__ import annotations

from sase.plan_chain import agent_family_role_for_suffix

DEFAULT_MONITOR_STOP_STATUS = "MONITORED"
MONITOR_FAMILY_ROLE = "monitor"
MONITOR_GLYPH = "⚙"
MONITOR_GLYPH_COLOR = "#FFAF5F"
MONITOR_PROC_ORIGIN = "monitor"
MONITOR_TIMEOUT_GLYPH = "⧖"

MONITOR_STATE_BUCKETS: dict[str, str] = {
    "running": "Running",
    "completed": "Done",
    "failed": "Failed",
    "timeout": "Failed",
    "stopped": "Done",
    "lost": "Failed",
}


def monitor_state_bucket(monitor_state: str | None) -> str:
    """Return the status bucket for a monitor's ``monitor_state``.

    An unrecognized or missing state buckets as ``Running`` so a monitor
    member that has not (yet) reached a terminal state never reads as
    finished.
    """
    return MONITOR_STATE_BUCKETS.get(monitor_state or "", "Running")


def monitor_state_is_terminal(monitor_state: str | None) -> bool:
    """Return whether ``monitor_state`` has reached a terminal bucket.

    Delegates to :func:`monitor_state_bucket` so the terminal-state set can
    never drift from the bucket map: an unrecognized or missing state
    buckets as ``Running`` and is therefore not terminal, so a monitor that
    has not (yet) reported never reads as finished.
    """
    return monitor_state_bucket(monitor_state) != "Running"


def is_monitor_member_role(
    agent_family_role: str | None,
    role_suffix: str | None = None,
) -> bool:
    """Return whether a row is a monitor member, not the monitor starter.

    ``monitor_id`` is written to both the monitor member and the agent that
    started it, so it cannot classify a row on its own. The explicit role wins;
    the suffix is a fallback for older metadata that omitted the role.
    """
    if isinstance(agent_family_role, str) and agent_family_role.strip():
        return agent_family_role.strip() == MONITOR_FAMILY_ROLE
    return agent_family_role_for_suffix(role_suffix) == MONITOR_FAMILY_ROLE


__all__ = [
    "DEFAULT_MONITOR_STOP_STATUS",
    "MONITOR_FAMILY_ROLE",
    "MONITOR_GLYPH",
    "MONITOR_GLYPH_COLOR",
    "MONITOR_PROC_ORIGIN",
    "MONITOR_STATE_BUCKETS",
    "MONITOR_TIMEOUT_GLYPH",
    "is_monitor_member_role",
    "monitor_state_bucket",
    "monitor_state_is_terminal",
]
