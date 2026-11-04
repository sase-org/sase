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
from .custody import (
    ACTIVE_CUSTODY_STATES,
    hijack_retains_claim,
    hijack_skips_claim_release,
    matching_active_record,
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
from .preview import (
    HijackContinuationPrompt,
    HijackRecoveryRefusal,
    RecoveryAction,
    RecoveryPreview,
    build_hijack_continuation_prompt,
    hijack_recovery_preview,
)
from .recover import (
    KEEP_WORK_ACTIONS,
    RECOVERY_LAUNCH_IDENTITY_ENV,
    RESULT_ALREADY_RESOLVED,
    RESULT_ALREADY_RESOLVING,
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_QUEUED,
    RESULT_REFUSED,
    RESULT_UNCERTAIN,
    InheritanceEvidence,
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    RecoveryTarget,
    recover_hijacked_agent,
    settle_recovery,
)
from .recovery_successor import (
    RecoveryLineage,
    require_recovery_inheritance,
    read_recovery_ack,
    rollback_recovery_preparation,
    write_recovery_ack,
)

HIJACK_RUNNER_CAPABILITY = "hijack"

__all__ = [
    "ACTIVE_CUSTODY_STATES",
    "HIJACK_RUNNER_CAPABILITY",
    "HijackLedgerConflict",
    "HijackContinuationPrompt",
    "HijackRecoveryRefusal",
    "InheritanceEvidence",
    "KEEP_WORK_ACTIONS",
    "RECOVERY_LAUNCH_IDENTITY_ENV",
    "RESULT_ALREADY_RESOLVED",
    "RESULT_ALREADY_RESOLVING",
    "RESULT_ERROR",
    "RESULT_LAUNCHED",
    "RESULT_QUEUED",
    "RESULT_REFUSED",
    "RESULT_UNCERTAIN",
    "RecoveryAction",
    "RecoveryDeps",
    "RecoveryLineage",
    "RecoveryPreview",
    "RecoveryRefusal",
    "RecoveryResult",
    "RecoverySubject",
    "RecoveryTarget",
    "advance_agent_hijack_record",
    "agent_hijack_eligibility",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
    "cas_advance_record",
    "build_hijack_continuation_prompt",
    "create_record",
    "hijack_retains_claim",
    "hijack_skips_claim_release",
    "hijack_recovery_preview",
    "list_active_records",
    "load_record",
    "load_record_by_agent_name",
    "load_record_by_artifacts_dir",
    "load_record_by_workspace",
    "mark_stopping_if_requested",
    "matching_active_record",
    "new_requested_record",
    "read_recovery_ack",
    "recover_hijacked_agent",
    "require_recovery_inheritance",
    "rollback_recovery_preparation",
    "settle_recovery",
    "write_recovery_ack",
]
