"""Hijacked-agent recovery policy (escalation ladder, successor context).

Rust (`sase_core::agent_hijack`) owns the ledger/eligibility state machine,
the never-downgrade rung walk, and the continuation-prompt text. This package
owns effects: config access, alias candidate assembly, the Python ledger
store, and the thin Rust bindings in :mod:`core`.
"""

from __future__ import annotations

from .core import (
    advance_agent_hijack_record,
    agent_hijack_eligibility,
    agent_hijack_status_for_done_marker,
    agent_hijack_wire_schema_version,
)
from .ledger import (
    HijackLedgerConflict,
    cas_advance_record,
    create_record,
    list_active_records,
    load_record,
    load_record_by_agent_name,
    load_record_by_artifacts_dir,
    load_record_by_workspace,
    mark_stopping_if_requested,
    new_requested_record,
)

HIJACK_RUNNER_CAPABILITY = "hijack"

__all__ = [
    "HIJACK_RUNNER_CAPABILITY",
    "HijackLedgerConflict",
    "advance_agent_hijack_record",
    "agent_hijack_eligibility",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
    "cas_advance_record",
    "create_record",
    "list_active_records",
    "load_record",
    "load_record_by_agent_name",
    "load_record_by_artifacts_dir",
    "load_record_by_workspace",
    "mark_stopping_if_requested",
    "new_requested_record",
]
