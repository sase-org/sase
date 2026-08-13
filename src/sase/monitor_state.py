"""Monitor state semantics shared by monitor storage and projections."""

from __future__ import annotations

from sase.plan_chain import agent_family_role_for_suffix

DEFAULT_MONITOR_STOP_STATUS = "MONITORED"
MONITOR_FAMILY_ROLE = "monitor"

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
    "MONITOR_STATE_BUCKETS",
    "is_monitor_member_role",
    "monitor_state_bucket",
]
