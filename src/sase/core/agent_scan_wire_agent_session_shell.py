"""Deprecated alias for :mod:`sase.core.agent_scan_wire_agent_session_turn`.

Kept for importers not yet moved to the turn spelling; new code should
import from ``agent_scan_wire_agent_session_turn``.
"""

from __future__ import annotations

from sase.core.agent_scan_wire_agent_session_turn import (
    AgentSessionShellGateWire,
    AgentSessionShellMonitorWire,
    AgentSessionShellWire,
    AgentSessionTurnGateWire,
    AgentSessionTurnMonitorWire,
    AgentSessionTurnWire,
    agent_session_shell_from_mapping,
    agent_session_turn_from_mapping,
)

__all__ = [
    "AgentSessionShellGateWire",
    "AgentSessionShellMonitorWire",
    "AgentSessionShellWire",
    "AgentSessionTurnGateWire",
    "AgentSessionTurnMonitorWire",
    "AgentSessionTurnWire",
    "agent_session_shell_from_mapping",
    "agent_session_turn_from_mapping",
]
