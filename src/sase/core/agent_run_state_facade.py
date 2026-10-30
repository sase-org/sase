"""Thin Python facade for the Rust-owned published agent-run state policy.

The Rust core classifies local state evidence, merges state precedence,
pages through published rows, and advances fair scheduled checkpoints.
Python supplies filesystem observations (marker files, dismissed bundles)
and performs publication writes.
"""

from __future__ import annotations

from sase.core.agent_run_state_wire import (
    AgentRunStateResolveRequestWire,
    AgentRunStateResolveResponseWire,
    AgentRunStateScheduleRequestWire,
    AgentRunStateScheduleResponseWire,
    AgentRunStateWindowRequestWire,
    AgentRunStateWindowResponseWire,
    agent_run_state_resolve_request_to_dict,
    agent_run_state_resolve_response_from_dict,
    agent_run_state_schedule_request_to_dict,
    agent_run_state_schedule_response_from_dict,
    agent_run_state_window_request_to_dict,
    agent_run_state_window_response_from_dict,
)
from sase.core.rust import require_rust_binding


def agent_run_state_wire_schema_version() -> int:
    """Return the agent-run state wire schema version from ``sase_core_rs``."""
    binding = require_rust_binding("agent_run_state_wire_schema_version")
    return int(binding())


def resolve_agent_run_state(
    request: AgentRunStateResolveRequestWire,
) -> AgentRunStateResolveResponseWire:
    """Resolve published state against local evidence through ``sase_core_rs``."""
    binding = require_rust_binding("resolve_agent_run_state")
    raw: dict[str, object] = binding(agent_run_state_resolve_request_to_dict(request))
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict run state decision")
    return agent_run_state_resolve_response_from_dict(raw)


def select_agent_run_state_window(
    request: AgentRunStateWindowRequestWire,
) -> AgentRunStateWindowResponseWire:
    """Select a deterministic bounded window through ``sase_core_rs``."""
    binding = require_rust_binding("select_agent_run_state_window")
    raw: dict[str, object] = binding(agent_run_state_window_request_to_dict(request))
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict run state window")
    return agent_run_state_window_response_from_dict(raw)


def advance_agent_run_state_schedule(
    request: AgentRunStateScheduleRequestWire,
) -> AgentRunStateScheduleResponseWire:
    """Advance the fair scheduled checkpoint through ``sase_core_rs``."""
    binding = require_rust_binding("advance_agent_run_state_schedule")
    raw: dict[str, object] = binding(agent_run_state_schedule_request_to_dict(request))
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict run state schedule")
    return agent_run_state_schedule_response_from_dict(raw)


__all__ = [
    "advance_agent_run_state_schedule",
    "agent_run_state_wire_schema_version",
    "resolve_agent_run_state",
    "select_agent_run_state_window",
]
