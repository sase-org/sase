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
    test_prepared_completion_failure_retains_dirty,
    test_prepared_completion_success_releases_clean,
    test_proc_reconcile_path_retains_dirty,
    test_repeated_settlement_is_idempotent,
    test_resume_degraded_and_failed_leave_hold,
    test_resume_transfer_settles_retention_record,
    test_stale_binding_retries_in_fresh_interpreter,
    test_stale_claim_is_noop,
    test_unavailable_owned_checkout_retains_as_uncertainty,
)
from .test_monitor_retention_settlement import (
    test_blocked_continuation_capture_retains_dirty,
    test_degraded_followup_retains_original_dirty_workspace,
    test_failed_monitor_with_failed_followup_releases_when_clean,
    test_failed_monitor_with_failed_followup_retains_dirty,
    test_reboot_lost_dirty_monitor_retains,
    test_same_workspace_successor_does_not_hold,
    test_stale_launch_label_without_proof_retains_dirty,
    test_stopped_clean_monitor_releases_claim,
    test_stopped_dirty_monitor_pins_claim_and_keeps_files,
)

__all__ = [
    "test_blocked_continuation_capture_retains_dirty",
    "test_degraded_followup_retains_original_dirty_workspace",
    "test_dirty_linked_repo_beyond_eighth_still_retains",
    "test_failed_monitor_with_failed_followup_releases_when_clean",
    "test_failed_monitor_with_failed_followup_retains_dirty",
    "test_prepared_completion_failure_retains_dirty",
    "test_prepared_completion_success_releases_clean",
    "test_proc_reconcile_path_retains_dirty",
    "test_reboot_lost_dirty_monitor_retains",
    "test_repeated_settlement_is_idempotent",
    "test_resume_degraded_and_failed_leave_hold",
    "test_resume_transfer_settles_retention_record",
    "test_same_workspace_successor_does_not_hold",
    "test_stale_binding_retries_in_fresh_interpreter",
    "test_stale_claim_is_noop",
    "test_stale_launch_label_without_proof_retains_dirty",
    "test_stopped_clean_monitor_releases_claim",
    "test_stopped_dirty_monitor_pins_claim_and_keeps_files",
    "test_unavailable_owned_checkout_retains_as_uncertainty",
]
