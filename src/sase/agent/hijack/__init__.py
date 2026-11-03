"""Hijacked-agent recovery policy (escalation ladder, successor context).

Rust (`sase_core::agent_hijack`) owns the ledger/eligibility state machine,
the never-downgrade rung walk, and the continuation-prompt text. This package
owns effects: config access, alias candidate assembly, and the thin Rust
bindings in :mod:`core`.
"""

from __future__ import annotations

from .core import (
    advance_agent_hijack_record,
    agent_hijack_eligibility,
    agent_hijack_status_for_done_marker,
    agent_hijack_wire_schema_version,
)

__all__ = [
    "advance_agent_hijack_record",
    "agent_hijack_eligibility",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
]
