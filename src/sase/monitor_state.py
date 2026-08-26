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

MONITOR_FAMILY_ROLE = "monitor"
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
_MONITOR_STATE_CONFIG = ShellStateConfig(
    family_role=MONITOR_FAMILY_ROLE,
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


def is_monitor_member_role(
    agent_family_role: str | None,
    role_suffix: str | None = None,
) -> bool:
    """Return whether a row is a monitor member, not the monitor starter.

    ``monitor_id`` is written to both the monitor member and the agent that
    started it, so it cannot classify a row on its own. The explicit role wins;
    the suffix is a fallback for older metadata that omitted the role.
    """
    return is_shell_member_role(
        agent_family_role,
        role_suffix,
        config=_MONITOR_STATE_CONFIG,
    )


def is_real_monitor_member(
    agent_family_role: str | None,
    monitor_id: str | None,
) -> bool:
    """Return whether a row is the durable monitor member for its family.

    ``monitor_id`` is inherited by the starter and later monitor-associated
    follow-ups, so the durable monitor predicate requires the explicit monitor
    role and a non-empty monitor id.
    """
    return is_real_shell_member(
        agent_family_role,
        monitor_id,
        config=_MONITOR_STATE_CONFIG,
    )


__all__ = [
    "DEFAULT_MONITOR_STOP_STATUS",
    "MONITOR_FAMILY_ROLE",
    "MONITOR_GLYPH",
    "MONITOR_GLYPH_COLOR",
    "MONITOR_PROC_ORIGIN",
    "MONITOR_SETTLED_GLYPH_COLOR",
    "MONITOR_STATE_BUCKETS",
    "MONITOR_TIMEOUT_GLYPH",
    "is_monitor_member_role",
    "is_real_monitor_member",
    "monitor_state_bucket",
    "monitor_state_is_terminal",
]
