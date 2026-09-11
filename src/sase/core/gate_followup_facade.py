"""Facade for Rust-backed gate follow-up disposition decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

GATE_FOLLOWUP_WIRE_SCHEMA_VERSION = 1


class GateFollowupWireError(ValueError):
    """Raised when the Rust gate-follow-up wire contract is incompatible."""


def gate_followup_wire_schema_version() -> int:
    """Return the installed gate-follow-up wire schema version."""
    binding = require_rust_binding("gate_followup_wire_schema_version")
    return int(binding())


def gate_followup_attempt_id(gate_id: str, fingerprint: str) -> str:
    """Return the stable attempt identity for one gate and fingerprint."""
    binding = require_rust_binding("gate_followup_attempt_id")
    return str(binding(gate_id, fingerprint))


def decide_gate_followup(request: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one gate handoff through the required Rust binding."""
    expected_schema = gate_followup_wire_schema_version()
    if expected_schema != GATE_FOLLOWUP_WIRE_SCHEMA_VERSION:
        raise GateFollowupWireError(
            "gate-followup binding schema mismatch: "
            f"got {expected_schema!r}, expected {GATE_FOLLOWUP_WIRE_SCHEMA_VERSION}"
        )
    actual_schema = request.get("schema_version")
    if actual_schema != expected_schema:
        raise ValueError(
            "gate follow-up wire schema mismatch: "
            f"got {actual_schema!r}, expected {expected_schema}"
        )
    binding = require_rust_binding("decide_gate_followup")
    return dict(binding(dict(request)))


__all__ = [
    "GATE_FOLLOWUP_WIRE_SCHEMA_VERSION",
    "GateFollowupWireError",
    "decide_gate_followup",
    "gate_followup_attempt_id",
    "gate_followup_wire_schema_version",
]
