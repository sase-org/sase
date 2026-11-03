"""Thin Python wrappers around the Rust-owned Agent Hijack policy.

The Rust core owns the ledger/eligibility state machine, the never-downgrade
rung walk, and the successor prompt text; Python owns config, evidence,
launches, and I/O. These wrappers pass plain JSON-shaped dicts straight
through :mod:`sase.core.rust` with no Python fallback: a missing binding means
the wheel predates the hijack feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from sase.core.agent_auto_restart_wire import AgentRecoveryWire
from sase.core.rust import require_rust_binding

ESCALATION_WIRE_SCHEMA_VERSION = 1
CONTINUATION_WIRE_SCHEMA_VERSION = 1


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


def escalation_wire_schema_version() -> int:
    """Return the hijack escalation wire schema version."""
    binding = require_rust_binding("agent_hijack_escalation_wire_schema_version")
    return int(binding())


def continuation_wire_schema_version() -> int:
    """Return the hijack continuation wire schema version."""
    binding = require_rust_binding("agent_hijack_continuation_wire_schema_version")
    return int(binding())


def normalize_hijack_rung(value: str) -> str:
    """Normalize a ladder rung to ``@``-prefixed canonical form."""
    binding = require_rust_binding("normalize_hijack_rung")
    return str(binding(value))


def hijack_escalation_target(request: dict[str, Any]) -> dict[str, Any]:
    """Compute the never-downgrade escalation target for a hijacked run.

    *request* mirrors ``AgentHijackEscalationRequestWire``: ``model_facts``,
    ``ladder``, ``alias_candidates``, ``lineage_to_rung``, and
    ``stalled_concrete``. Returns the result wire dict with ``available``,
    ``kind`` (``escalate``/``switch``), ``from_rung``, ``to_rung``,
    ``concrete``, and ``reason``.
    """
    binding = require_rust_binding("agent_hijack_escalation_target")
    return dict(binding(request))


def hijack_continuation_prompt(request: dict[str, Any]) -> str:
    """Build the continuation prompt for a hijack successor."""
    binding = require_rust_binding("agent_hijack_continuation_prompt")
    return str(binding(request))


def strip_hijack_launch_directives(prompt: str) -> str:
    """Strip launch-only directives, preserving fenced code blocks."""
    binding = require_rust_binding("strip_hijack_launch_directives")
    return str(binding(prompt))


__all__ = [
    "CONTINUATION_WIRE_SCHEMA_VERSION",
    "ESCALATION_WIRE_SCHEMA_VERSION",
    "advance_agent_hijack_record",
    "agent_hijack_eligibility",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
    "continuation_wire_schema_version",
    "escalation_wire_schema_version",
    "hijack_continuation_prompt",
    "hijack_escalation_target",
    "normalize_hijack_rung",
    "strip_hijack_launch_directives",
]
