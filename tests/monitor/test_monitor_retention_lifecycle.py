"""Monitor retention: completion, resume, and edge-case paths.

The lifecycle tests now live in :mod:`test_monitor_retention_lifecycle_completion`,
:mod:`test_monitor_retention_lifecycle_resume`, and
:mod:`test_monitor_retention_lifecycle_baselines`; this module re-exports their
public test functions so the existing import path keeps working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_monitor_retention_lifecycle_baselines import (
    test_dirty_linked_repo_beyond_eighth_still_retains,
    test_discovery_failure_with_dirty_opened_linked_retains,
    test_failed_git_preflight_without_baseline_retains,
    test_foreign_starter_evidence_releases_clean_workspace,
    test_retained_monitor_stores_exactly_one_notification,
    test_same_workspace_starter_baseline_still_contributes,
    test_stale_binding_retries_in_fresh_interpreter,
    test_unavailable_owned_checkout_retains_as_uncertainty,
)
from .test_monitor_retention_lifecycle_completion import (
    test_prepared_completion_failure_retains_dirty,
    test_prepared_completion_success_releases_clean,
    test_proc_reconcile_path_retains_dirty,
    test_repeated_settlement_is_idempotent,
    test_repo_less_command_releases,
    test_stale_claim_is_noop,
    test_unchanged_foreign_baseline_dirt_releases,
)
from .test_monitor_retention_lifecycle_resume import (
    test_fresh_interpreter_timeout_pins_dirty_claim,
    test_pending_write_failure_still_pins,
    test_resume_degraded_and_failed_leave_hold,
    test_resume_success_label_without_proof_leaves_hold,
    test_resume_transfer_with_live_successor_settles,
    test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp,
    test_successor_collection_failure_pins_dirty_claim,
)

__all__ = [
    "test_dirty_linked_repo_beyond_eighth_still_retains",
    "test_discovery_failure_with_dirty_opened_linked_retains",
    "test_failed_git_preflight_without_baseline_retains",
    "test_foreign_starter_evidence_releases_clean_workspace",
    "test_fresh_interpreter_timeout_pins_dirty_claim",
    "test_pending_write_failure_still_pins",
    "test_prepared_completion_failure_retains_dirty",
    "test_prepared_completion_success_releases_clean",
    "test_proc_reconcile_path_retains_dirty",
    "test_repeated_settlement_is_idempotent",
    "test_repo_less_command_releases",
    "test_resume_degraded_and_failed_leave_hold",
    "test_resume_success_label_without_proof_leaves_hold",
    "test_resume_transfer_with_live_successor_settles",
    "test_retained_monitor_stores_exactly_one_notification",
    "test_same_workspace_starter_baseline_still_contributes",
    "test_stale_binding_retries_in_fresh_interpreter",
    "test_stale_claim_is_noop",
    "test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp",
    "test_successor_collection_failure_pins_dirty_claim",
    "test_unavailable_owned_checkout_retains_as_uncertainty",
    "test_unchanged_foreign_baseline_dirt_releases",
]
