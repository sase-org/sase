"""Monitor state semantics shared by monitor storage and projections."""

from __future__ import annotations

from sase.monitor_status import DEFAULT_MONITOR_STOP_STATUS
from sase.shells.state import (
    ShellStateConfig,
    is_real_shell_member,
    is_shell_member_role,
    shell_state_bucket,
    shell_state_is_terminal,
)

MONITOR_AGENT_SESSION_ROLE = "monitor"
MONITOR_GLYPH = "⚙"
MONITOR_GLYPH_COLOR = "#FFAF5F"
#: Finished-monitor lane hue, shared by row and panel-title badges.
MONITOR_SETTLED_GLYPH_COLOR = "#9E9E9E"
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

#: Follow-up outcomes that mean a settled monitor handed its lane to a
#: successor agent. Mirrors ``SUCCESSFUL_SHELL_FOLLOWUP_OUTCOMES`` in
#: ``sase.core.wait_dependency_resolution`` without importing the monitor
#: supervisor stack onto TUI hot paths.
MONITOR_HANDOFF_FOLLOWUP_OUTCOMES = frozenset({"launched", "launched-degraded"})
#: Follow-up outcome recorded when the host completes a monitor's follow-up.
MONITOR_HOST_COMPLETED_OUTCOME = "host-completed"
#: Host-completion status recorded when the host completes a monitor's follow-up.
MONITOR_HOST_COMPLETED_STATUS = "completed_by_host"
_MONITOR_STATE_CONFIG = ShellStateConfig(
    agent_session_role=MONITOR_AGENT_SESSION_ROLE,
    buckets=MONITOR_STATE_BUCKETS,
)


def monitor_state_bucket(monitor_state: str | None) -> str:
    """Return the status bucket for a monitor's ``monitor_state``.

    An unrecognized or missing state buckets as ``Running`` so a monitor
    member that has not (yet) reached a terminal state never reads as
    finished.
    """
    return shell_state_bucket(monitor_state, _MONITOR_STATE_CONFIG)


def monitor_state_is_terminal(monitor_state: str | None) -> bool:
    """Return whether ``monitor_state`` has reached a terminal bucket.

    Delegates to :func:`monitor_state_bucket` so the terminal-state set can
    never drift from the bucket map: an unrecognized or missing state
    buckets as ``Running`` and is therefore not terminal, so a monitor that
    has not (yet) reported never reads as finished.
    """
    return shell_state_is_terminal(monitor_state, _MONITOR_STATE_CONFIG)


def monitor_lane_status_bucket(
    monitor_state: str | None,
    own_bucket: str,
    *,
    followup_outcome: str | None = None,
    followup_error: str | None = None,
    next_action: str | None = None,
    host_completion_status: str | None = None,
) -> str:
    """Return the agent-level lane bucket for one settled monitor row.

    A monitor's own bucket describes its command, not an agent. Agent-level
    aggregates read a monitor only as the current state of its lane:

    - A continuation that was launched or is pending keeps the lane in
      progress (``Running``).
    - A continuation that failed to launch, or no continuation at all, leaves
      the monitor's own bucket standing as a real, actionable failure.
    - Host completion settles the lane as ``Done``.
    """
    if not monitor_state_is_terminal(monitor_state):
        return own_bucket
    if isinstance(followup_error, str) and followup_error.strip():
        return own_bucket
    if (
        followup_outcome == MONITOR_HOST_COMPLETED_OUTCOME
        or host_completion_status == MONITOR_HOST_COMPLETED_STATUS
    ):
        return "Done"
    if followup_outcome in MONITOR_HANDOFF_FOLLOWUP_OUTCOMES:
        return "Running"
    if (
        monitor_state not in {"lost", "stopped"}
        and followup_outcome is None
        and isinstance(next_action, str)
        and next_action.strip()
    ):
        return "Running"
    return own_bucket


def is_monitor_member_role(
    agent_session_role: str | None,
    role_suffix: str | None = None,
) -> bool:
    """Return whether a row is a monitor member, not the monitor starter.

    ``monitor_id`` is written to both the monitor member and the agent that
    started it, so it cannot classify a row on its own. The explicit role wins;
    the suffix is a fallback for older metadata that omitted the role.
    """
    return is_shell_member_role(
        agent_session_role,
        role_suffix,
        config=_MONITOR_STATE_CONFIG,
    )


def is_real_monitor_member(
    agent_session_role: str | None,
    monitor_id: str | None,
) -> bool:
    """Return whether a row is the durable monitor member for its agent session.

    ``monitor_id`` is inherited by the starter and later monitor-associated
    follow-ups, so the durable monitor predicate requires the explicit monitor
    role and a non-empty monitor id.
    """
    return is_real_shell_member(
        agent_session_role,
        monitor_id,
        config=_MONITOR_STATE_CONFIG,
    )


__all__ = [
    "DEFAULT_MONITOR_STOP_STATUS",
    "MONITOR_AGENT_SESSION_ROLE",
    "MONITOR_GLYPH",
    "MONITOR_GLYPH_COLOR",
    "MONITOR_HANDOFF_FOLLOWUP_OUTCOMES",
    "MONITOR_HOST_COMPLETED_OUTCOME",
    "MONITOR_HOST_COMPLETED_STATUS",
    "MONITOR_PROC_ORIGIN",
    "MONITOR_SETTLED_GLYPH_COLOR",
    "MONITOR_STATE_BUCKETS",
    "MONITOR_TIMEOUT_GLYPH",
    "is_monitor_member_role",
    "is_real_monitor_member",
    "monitor_lane_status_bucket",
    "monitor_state_bucket",
    "monitor_state_is_terminal",
]
