"""Facade preserving the historic ``tests.monitor.test_monitor_retention`` import path.

The retention tests now live in :mod:`test_monitor_retention_settlement` and
:mod:`test_monitor_retention_lifecycle`; this module re-exports their public
test functions so existing import paths keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_monitor_retention_lifecycle import (
    test_dirty_linked_repo_beyond_eighth_still_retains,
    test_discovery_failure_with_dirty_opened_linked_retains,
    test_failed_git_preflight_without_baseline_retains,
    test_fresh_interpreter_timeout_pins_dirty_claim,
    test_pending_write_failure_still_pins,
    test_prepared_completion_failure_retains_dirty,
    test_prepared_completion_success_releases_clean,
    test_proc_reconcile_path_retains_dirty,
    test_repeated_settlement_is_idempotent,
    test_repo_less_command_releases,
    test_resume_degraded_and_failed_leave_hold,
    test_resume_success_label_without_proof_leaves_hold,
    test_resume_transfer_with_live_successor_settles,
    test_stale_binding_retries_in_fresh_interpreter,
    test_stale_claim_is_noop,
    test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp,
    test_successor_collection_failure_pins_dirty_claim,
    test_unavailable_owned_checkout_retains_as_uncertainty,
    test_unchanged_foreign_baseline_dirt_releases,
)
from .test_monitor_retention_settlement import (
    test_blocked_continuation_capture_retains_dirty,
    test_degraded_delivery_does_not_prove_same_workspace_transfer,
    test_degraded_followup_retains_original_dirty_workspace,
    test_delivery_history_without_live_successor_retains,
    test_different_workspace_occupant_does_not_prove_transfer,
    test_failed_monitor_with_failed_followup_releases_when_clean,
    test_failed_monitor_with_failed_followup_retains_dirty,
    test_live_receiver_without_transferred_claim_retains,
    test_reboot_lost_dirty_monitor_retains,
    test_same_workspace_successor_keeps_transferred_claim,
    test_stale_launch_label_without_proof_retains_dirty,
    test_stopped_clean_monitor_releases_claim,
    test_stopped_dirty_monitor_pins_claim_and_keeps_files,
    test_wrong_result_id_delivery_does_not_prove_transfer,
)

__all__ = [
    "test_blocked_continuation_capture_retains_dirty",
    "test_degraded_delivery_does_not_prove_same_workspace_transfer",
    "test_degraded_followup_retains_original_dirty_workspace",
    "test_delivery_history_without_live_successor_retains",
    "test_different_workspace_occupant_does_not_prove_transfer",
    "test_dirty_linked_repo_beyond_eighth_still_retains",
    "test_discovery_failure_with_dirty_opened_linked_retains",
    "test_failed_git_preflight_without_baseline_retains",
    "test_failed_monitor_with_failed_followup_releases_when_clean",
    "test_failed_monitor_with_failed_followup_retains_dirty",
    "test_fresh_interpreter_timeout_pins_dirty_claim",
    "test_live_receiver_without_transferred_claim_retains",
    "test_pending_write_failure_still_pins",
    "test_prepared_completion_failure_retains_dirty",
    "test_prepared_completion_success_releases_clean",
    "test_proc_reconcile_path_retains_dirty",
    "test_reboot_lost_dirty_monitor_retains",
    "test_repeated_settlement_is_idempotent",
    "test_repo_less_command_releases",
    "test_resume_degraded_and_failed_leave_hold",
    "test_resume_success_label_without_proof_leaves_hold",
    "test_resume_transfer_with_live_successor_settles",
    "test_same_workspace_successor_keeps_transferred_claim",
    "test_stale_binding_retries_in_fresh_interpreter",
    "test_stale_claim_is_noop",
    "test_stale_launch_label_without_proof_retains_dirty",
    "test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp",
    "test_stopped_clean_monitor_releases_claim",
    "test_stopped_dirty_monitor_pins_claim_and_keeps_files",
    "test_successor_collection_failure_pins_dirty_claim",
    "test_unavailable_owned_checkout_retains_as_uncertainty",
    "test_unchanged_foreign_baseline_dirt_releases",
    "test_wrong_result_id_delivery_does_not_prove_transfer",
]
