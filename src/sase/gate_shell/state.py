"""Gate-shell state semantics shared by storage and cleanup."""

from __future__ import annotations

from sase.agent.status_buckets import (
    HANDOFF_SETTLED_STATUSES,
    status_bucket_for_values,
)
from sase.monitor_state import MONITOR_STATE_BUCKETS
from sase.shells.state import (
    ShellStateConfig,
    is_real_shell_member,
    is_shell_member_role,
    shell_state_bucket,
)

GATE_FAMILY_ROLE = "gate"
GATE_GLYPH = "⋔"
GATE_SETTLED_GLYPH_COLOR = "#9E9E9E"
GATE_FAILURE_GLYPH_COLOR = "#FF5F5F"
GATE_STATE_BUCKETS: dict[str, str] = {
    "pending": "Stopped",
    "settling": "Running",
    **MONITOR_STATE_BUCKETS,
    "answered": "Done",
}
TERMINAL_GATE_STATES = frozenset(
    {"answered", "completed", "failed", "timeout", "stopped", "lost"}
)

_GATE_STATE_CONFIG = ShellStateConfig(
    family_role=GATE_FAMILY_ROLE,
    buckets=GATE_STATE_BUCKETS,
)


def _gate_state_bucket(gate_state: str | None) -> str:
    """Return the display bucket for ``gate_state``."""
    return shell_state_bucket(gate_state, _GATE_STATE_CONFIG)


def gate_member_status_bucket(gate_state: str | None, status: str | None) -> str:
    """Return the display bucket for a gate member row showing *status*.

    A gate that settled into a handoff status (an approved plan, an answered
    question) launched a successor instead of finishing, so the row keeps the
    ``Running`` bucket its status implies.  Every other state -- pending,
    settling, rejected, cancelled, timed out, failed -- keeps the bucket its
    gate state implies.
    """
    if status in HANDOFF_SETTLED_STATUSES:
        return status_bucket_for_values(status)
    return _gate_state_bucket(gate_state)


def gate_state_is_terminal(gate_state: str | None) -> bool:
    """Return whether ``gate_state`` has reached a terminal outcome."""
    return gate_state in TERMINAL_GATE_STATES


def _is_gate_member_role(
    agent_family_role: str | None,
    role_suffix: str | None = None,
) -> bool:
    """Return whether metadata identifies a gate shell member."""
    return is_shell_member_role(
        agent_family_role,
        role_suffix,
        config=_GATE_STATE_CONFIG,
    )


def is_real_gate_member(agent_family_role: str | None, gate_id: str | None) -> bool:
    """Return whether metadata identifies a durable gate-shell member."""
    return _is_gate_member_role(agent_family_role) and is_real_shell_member(
        agent_family_role, gate_id, config=_GATE_STATE_CONFIG
    )


__all__ = [
    "GATE_FAMILY_ROLE",
    "GATE_FAILURE_GLYPH_COLOR",
    "GATE_GLYPH",
    "GATE_SETTLED_GLYPH_COLOR",
    "GATE_STATE_BUCKETS",
    "TERMINAL_GATE_STATES",
    "gate_member_status_bucket",
    "gate_state_is_terminal",
    "is_real_gate_member",
]
