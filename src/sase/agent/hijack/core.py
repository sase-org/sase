"""Thin Python wrappers around the Rust-owned Agent Hijack policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from sase.core.agent_auto_restart_wire import AgentRecoveryWire
from sase.core.rust import require_rust_binding


def agent_hijack_wire_schema_version() -> int:
    """Return the Agent Hijack wire schema version from ``sase_core_rs``."""
    binding = require_rust_binding("agent_hijack_wire_schema_version")
    return int(binding())


def advance_agent_hijack_record(
    record: Mapping[str, Any], event: Mapping[str, Any]
) -> dict[str, Any]:
    """Advance one hijack record through the core state machine."""
    binding = require_rust_binding("advance_agent_hijack_record")
    return dict(binding(dict(record), dict(event)))


def agent_hijack_eligibility(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a local agent row against the v1 hijack rules."""
    binding = require_rust_binding("agent_hijack_eligibility")
    return dict(binding(dict(facts)))


def agent_hijack_status_for_done_marker(
    outcome: str | None, recovery: Mapping[str, Any] | AgentRecoveryWire | None
) -> str | None:
    """Derive the user-facing status from hijack done-marker facts."""
    if recovery is None:
        recovery_data = None
    elif isinstance(recovery, Mapping):
        recovery_data = dict(recovery)
    elif is_dataclass(recovery):
        recovery_data = asdict(recovery)
    else:
        raise TypeError("recovery must be a mapping, dataclass, or None")
    binding = require_rust_binding("agent_hijack_status_for_done_marker")
    status = binding(outcome, recovery_data)
    return None if status is None else str(status)


__all__ = [
    "advance_agent_hijack_record",
    "agent_hijack_eligibility",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
]
