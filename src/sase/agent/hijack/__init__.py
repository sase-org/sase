"""Hijacked-agent recovery policy (escalation ladder, successor context).

Rust (`sase_core::agent_hijack`) owns the ledger/eligibility state machine,
the never-downgrade rung walk, and the continuation-prompt text. This package
owns effects: config access, alias candidate assembly, the Python ledger
store, and the thin Rust bindings in :mod:`core`.

Lock order (outer to inner): adoption, gate/monitor lane, gate follow-up,
hijack ledger/target index, then ``patch_lock``. Hijack-package sub-order is
``target_index``, ``apply``, ``record``, ``patch_lock``. Terminal cleanup may
acquire ``target_index`` while already holding ``record``. The ledger/target
lock is never taken from inside ``patch_lock``.

Package-level names resolve lazily (PEP 562) so the always-on stale-running
sweep, which only needs ``sase.agent.hijack.ledger``, does not import the
preview/recover graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "ACTIVE_CUSTODY_STATES": ("sase.agent.hijack.custody", "ACTIVE_CUSTODY_STATES"),
    "HijackContinuationPrompt": (
        "sase.agent.hijack.preview",
        "HijackContinuationPrompt",
    ),
    "HijackLatchedError": ("sase.agent.hijack.spawn_guard", "HijackLatchedError"),
    "HijackLedgerConflict": ("sase.agent.hijack.ledger", "HijackLedgerConflict"),
    "HijackRecoveryRefusal": ("sase.agent.hijack.preview", "HijackRecoveryRefusal"),
    "InheritanceEvidence": ("sase.agent.hijack.recover", "InheritanceEvidence"),
    "KEEP_WORK_ACTIONS": ("sase.agent.hijack.recover", "KEEP_WORK_ACTIONS"),
    "RECOVERY_LAUNCH_IDENTITY_ENV": (
        "sase.agent.hijack.recover",
        "RECOVERY_LAUNCH_IDENTITY_ENV",
    ),
    "RELEASE_ACTIONS": ("sase.agent.hijack.recover_release", "RELEASE_ACTIONS"),
    "RESULT_ALREADY_RESOLVED": ("sase.agent.hijack.recover", "RESULT_ALREADY_RESOLVED"),
    "RESULT_ALREADY_RESOLVING": (
        "sase.agent.hijack.recover",
        "RESULT_ALREADY_RESOLVING",
    ),
    "RESULT_ERROR": ("sase.agent.hijack.recover", "RESULT_ERROR"),
    "RESULT_LAUNCHED": ("sase.agent.hijack.recover", "RESULT_LAUNCHED"),
    "RESULT_QUEUED": ("sase.agent.hijack.recover", "RESULT_QUEUED"),
    "RESULT_REFUSED": ("sase.agent.hijack.recover", "RESULT_REFUSED"),
    "RESULT_UNCERTAIN": ("sase.agent.hijack.recover", "RESULT_UNCERTAIN"),
    "RecoveryAction": ("sase.agent.hijack.preview", "RecoveryAction"),
    "RecoveryDeps": ("sase.agent.hijack.recover", "RecoveryDeps"),
    "RecoveryLineage": ("sase.agent.hijack.recovery_successor", "RecoveryLineage"),
    "RecoveryPreview": ("sase.agent.hijack.preview", "RecoveryPreview"),
    "RecoveryRefusal": ("sase.agent.hijack.recover", "RecoveryRefusal"),
    "RecoveryResult": ("sase.agent.hijack.recover", "RecoveryResult"),
    "RecoverySubject": ("sase.agent.hijack.recover", "RecoverySubject"),
    "RecoveryTarget": ("sase.agent.hijack.recover", "RecoveryTarget"),
    "ReleaseDeps": ("sase.agent.hijack.recover_release", "ReleaseDeps"),
    "ReleaseEffectDeps": ("sase.agent.hijack._release_effects", "ReleaseEffectDeps"),
    "abandon_stop_blocked_for_workspace": (
        "sase.agent.hijack.custody",
        "abandon_stop_blocked_for_workspace",
    ),
    "advance_agent_hijack_record": (
        "sase.agent.hijack.core",
        "advance_agent_hijack_record",
    ),
    "agent_hijack_decide": ("sase.agent.hijack.core", "agent_hijack_decide"),
    "agent_hijack_eligibility": ("sase.agent.hijack.core", "agent_hijack_eligibility"),
    "agent_hijack_eligibility_wire_schema_version": (
        "sase.agent.hijack.core",
        "agent_hijack_eligibility_wire_schema_version",
    ),
    "agent_hijack_latch_observe": (
        "sase.agent.hijack.core",
        "agent_hijack_latch_observe",
    ),
    "agent_hijack_latch_wire_schema_version": (
        "sase.agent.hijack.core",
        "agent_hijack_latch_wire_schema_version",
    ),
    "agent_hijack_select_occupant": (
        "sase.agent.hijack.core",
        "agent_hijack_select_occupant",
    ),
    "agent_hijack_status_for_done_marker": (
        "sase.agent.hijack.core",
        "agent_hijack_status_for_done_marker",
    ),
    "agent_hijack_wire_schema_version": (
        "sase.agent.hijack.core",
        "agent_hijack_wire_schema_version",
    ),
    "apply_latch_at_boundary": ("sase.agent.hijack.latch", "apply_latch_at_boundary"),
    "build_hijack_continuation_prompt": (
        "sase.agent.hijack.preview",
        "build_hijack_continuation_prompt",
    ),
    "cancel_latch": ("sase.agent.hijack.latch", "cancel_latch"),
    "cancel_recovery_admission_for_rollback": (
        "sase.agent.hijack.recovery_admission",
        "cancel_recovery_admission_for_rollback",
    ),
    "cancel_recovery_admission_request": (
        "sase.agent.hijack.recovery_admission",
        "cancel_recovery_admission_request",
    ),
    "cas_advance_record": ("sase.agent.hijack.ledger", "cas_advance_record"),
    "create_record": ("sase.agent.hijack.ledger", "create_record"),
    "dismiss_resolved": ("sase.agent.hijack._release_effects", "dismiss_resolved"),
    "ensure_recovery_snapshot": (
        "sase.agent.hijack._release_snapshot",
        "ensure_recovery_snapshot",
    ),
    "force_hijack_latch": ("sase.agent.hijack.latch", "force_hijack_latch"),
    "hijack_latch_force_eligibility": (
        "sase.agent.hijack.core",
        "hijack_latch_force_eligibility",
    ),
    "hijack_latch_reconcile": ("sase.agent.hijack.core", "hijack_latch_reconcile"),
    "hijack_recovery_confirm": ("sase.agent.hijack.core", "hijack_recovery_confirm"),
    "hijack_recovery_preview": ("sase.agent.hijack.preview", "hijack_recovery_preview"),
    "hijack_recovery_rollback": ("sase.agent.hijack.core", "hijack_recovery_rollback"),
    "hijack_retains_claim": ("sase.agent.hijack.custody", "hijack_retains_claim"),
    "hijack_skips_claim_release": (
        "sase.agent.hijack.custody",
        "hijack_skips_claim_release",
    ),
    "list_active_records": ("sase.agent.hijack.ledger", "list_active_records"),
    "load_record": ("sase.agent.hijack.ledger", "load_record"),
    "load_record_by_agent_name": (
        "sase.agent.hijack.ledger",
        "load_record_by_agent_name",
    ),
    "load_record_by_artifacts_dir": (
        "sase.agent.hijack.ledger",
        "load_record_by_artifacts_dir",
    ),
    "load_record_by_workspace": (
        "sase.agent.hijack.ledger",
        "load_record_by_workspace",
    ),
    "mark_stopping_if_requested": (
        "sase.agent.hijack.ledger",
        "mark_stopping_if_requested",
    ),
    "matching_active_record": ("sase.agent.hijack.custody", "matching_active_record"),
    "moot_latch": ("sase.agent.hijack.latch", "moot_latch"),
    "new_requested_record": ("sase.agent.hijack.ledger", "new_requested_record"),
    "observe_hijack_latch": ("sase.agent.hijack.latch", "observe_hijack_latch"),
    "observe_recovery_admission": (
        "sase.agent.hijack.recovery_admission",
        "observe_recovery_admission",
    ),
    "read_recovery_ack": ("sase.agent.hijack.recovery_successor", "read_recovery_ack"),
    "recover_hijacked_agent": ("sase.agent.hijack.recover", "recover_hijacked_agent"),
    "recover_release_action": (
        "sase.agent.hijack.recover_release",
        "recover_release_action",
    ),
    "request_latch": ("sase.agent.hijack.latch", "request_latch"),
    "require_recovery_inheritance": (
        "sase.agent.hijack.recovery_successor",
        "require_recovery_inheritance",
    ),
    "resolving_record_for_workspace": (
        "sase.agent.hijack.custody",
        "resolving_record_for_workspace",
    ),
    "restart_availability_reason": (
        "sase.agent.hijack.recover_release",
        "restart_availability_reason",
    ),
    "restart_replacement_conflicts": (
        "sase.agent.hijack.recover_release",
        "restart_replacement_conflicts",
    ),
    "restart_resolved": ("sase.agent.hijack._release_effects", "restart_resolved"),
    "resume_recovery_admission": (
        "sase.agent.hijack.recovery_admission",
        "resume_recovery_admission",
    ),
    "rollback_recovery_preparation": (
        "sase.agent.hijack.recovery_successor",
        "rollback_recovery_preparation",
    ),
    "settle_recovery": ("sase.agent.hijack.recover", "settle_recovery"),
    "write_recovery_ack": (
        "sase.agent.hijack.recovery_successor",
        "write_recovery_ack",
    ),
}

if TYPE_CHECKING:
    from .core import (
        advance_agent_hijack_record,
        agent_hijack_decide,
        agent_hijack_eligibility,
        agent_hijack_eligibility_wire_schema_version,
        agent_hijack_latch_observe,
        agent_hijack_latch_wire_schema_version,
        agent_hijack_select_occupant,
        agent_hijack_status_for_done_marker,
        agent_hijack_wire_schema_version,
        hijack_recovery_confirm,
        hijack_recovery_rollback,
        hijack_latch_force_eligibility,
        hijack_latch_reconcile,
    )
    from .custody import (
        ACTIVE_CUSTODY_STATES,
        abandon_stop_blocked_for_workspace,
        hijack_retains_claim,
        hijack_skips_claim_release,
        matching_active_record,
        resolving_record_for_workspace,
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
    from .recovery_admission import (
        cancel_recovery_admission_for_rollback,
        cancel_recovery_admission_request,
        observe_recovery_admission,
        resume_recovery_admission,
    )
    from ._release_effects import (
        ReleaseEffectDeps,
        dismiss_resolved,
        restart_resolved,
    )
    from ._release_snapshot import (
        ensure_recovery_snapshot,
    )
    from .recover_release import (
        RELEASE_ACTIONS,
        ReleaseDeps,
        recover_release_action,
        restart_availability_reason,
        restart_replacement_conflicts,
    )
    from .latch import (
        apply_latch_at_boundary,
        cancel_latch,
        force_hijack_latch,
        moot_latch,
        observe_hijack_latch,
        request_latch,
    )
    from .spawn_guard import (
        HijackLatchedError,
    )

HIJACK_RUNNER_CAPABILITY = "hijack"
MISSING_HIJACK_CAPABILITY_MESSAGE = (
    "runner did not record hijack support; use x, or wait for its next turn"
)

__all__ = [
    "ACTIVE_CUSTODY_STATES",
    "abandon_stop_blocked_for_workspace",
    "HIJACK_RUNNER_CAPABILITY",
    "MISSING_HIJACK_CAPABILITY_MESSAGE",
    "HijackLedgerConflict",
    "HijackLatchedError",
    "HijackContinuationPrompt",
    "HijackRecoveryRefusal",
    "InheritanceEvidence",
    "KEEP_WORK_ACTIONS",
    "RELEASE_ACTIONS",
    "RECOVERY_LAUNCH_IDENTITY_ENV",
    "ReleaseDeps",
    "ReleaseEffectDeps",
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
    "agent_hijack_decide",
    "agent_hijack_eligibility",
    "agent_hijack_eligibility_wire_schema_version",
    "agent_hijack_latch_observe",
    "agent_hijack_latch_wire_schema_version",
    "agent_hijack_select_occupant",
    "agent_hijack_status_for_done_marker",
    "agent_hijack_wire_schema_version",
    "cas_advance_record",
    "cancel_recovery_admission_request",
    "cancel_recovery_admission_for_rollback",
    "build_hijack_continuation_prompt",
    "create_record",
    "hijack_retains_claim",
    "hijack_skips_claim_release",
    "hijack_recovery_preview",
    "hijack_recovery_confirm",
    "hijack_recovery_rollback",
    "hijack_latch_force_eligibility",
    "hijack_latch_reconcile",
    "apply_latch_at_boundary",
    "cancel_latch",
    "force_hijack_latch",
    "moot_latch",
    "observe_hijack_latch",
    "request_latch",
    "list_active_records",
    "load_record",
    "load_record_by_agent_name",
    "load_record_by_artifacts_dir",
    "load_record_by_workspace",
    "mark_stopping_if_requested",
    "matching_active_record",
    "new_requested_record",
    "resolving_record_for_workspace",
    "observe_recovery_admission",
    "dismiss_resolved",
    "ensure_recovery_snapshot",
    "read_recovery_ack",
    "recover_hijacked_agent",
    "recover_release_action",
    "restart_availability_reason",
    "restart_replacement_conflicts",
    "restart_resolved",
    "require_recovery_inheritance",
    "rollback_recovery_preparation",
    "resume_recovery_admission",
    "settle_recovery",
    "write_recovery_ack",
]


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__
