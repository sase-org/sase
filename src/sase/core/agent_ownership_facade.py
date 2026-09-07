"""Facade for Rust-backed agent ownership batch planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def agent_ownership_batch_wire_schema_version() -> int:
    """Return the installed ownership-batch wire schema version."""
    binding = require_rust_binding("agent_ownership_batch_wire_schema_version")
    return int(binding())


def plan_agent_ownership_batch(request: Mapping[str, Any]) -> dict[str, Any]:
    """Plan ownership and registry reservation decisions through Rust."""
    expected_schema = agent_ownership_batch_wire_schema_version()
    actual_schema = request.get("schema_version")
    if actual_schema != expected_schema:
        raise ValueError(
            "agent ownership batch wire schema mismatch: "
            f"got {actual_schema!r}, expected {expected_schema}"
        )
    binding = require_rust_binding("plan_agent_ownership_batch")
    return dict(binding(dict(request)))


__all__ = [
    "agent_ownership_batch_wire_schema_version",
    "plan_agent_ownership_batch",
]
