"""Tests for axe_runner_utils module.

Split into focused modules; this module re-exports every public name so the
original import path keeps working. It collects no tests itself. Only public
names are re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

from tests.test_axe_runner_utils_artifacts import (
    test_all_steps_hidden_all_hidden,
    test_all_steps_hidden_empty_steps,
    test_all_steps_hidden_missing_file,
    test_all_steps_hidden_mixed,
    test_all_steps_hidden_no_hidden_key,
    test_all_steps_hidden_skipped_steps_ignored,
    test_all_steps_hidden_visible_completed_step,
    test_clear_agent_meta_tribe_removes_canonical_and_legacy_keys,
    test_clear_agent_meta_tribe_safe_noops,
    test_detect_write_and_persist_review_agent_meta,
    test_write_done_marker_can_write_visible_review_agent,
)
from tests.test_axe_runner_utils_reporting import (
    test_finalize_axe_runner_handles_errors,
    test_finalize_axe_runner_no_matching_patch,
    test_finalize_axe_runner_success,
    test_no_proposal_summary_prefers_generic_finalizer_result,
    test_no_proposal_summary_reads_historical_commit_result_only,
)
from tests.test_axe_runner_utils_signals import (
    test_reset_killed_clears_timestamp,
    test_sigterm_handler_can_be_rearmed,
    test_sigterm_handler_contains_logging_failure,
    test_sigterm_handler_hard_mode_exits_once,
    test_sigterm_handler_ignores_nested_delivery,
    test_sigterm_handler_repeated_delivery_is_a_noop,
    test_sigterm_handler_runs_cleanup_callback,
    test_sigterm_handler_sets_killed,
    test_sigterm_handler_subprocess_survives_signal_burst,
    test_sigterm_handler_writes_without_buffered_stderr,
)
from tests.test_axe_runner_utils_workspace import (
    test_clear_stale_git_index_lock_keeps_fresh_lock,
    test_clear_stale_git_index_lock_no_lock_is_noop,
    test_clear_stale_git_index_lock_removes_abandoned_lock,
    test_prepare_workspace_clean_fails,
    test_prepare_workspace_clears_stale_lock_before_clean,
    test_prepare_workspace_default_parent_sync_failure_fails,
    test_prepare_workspace_default_parent_sync_not_implemented_passes,
    test_prepare_workspace_default_parent_syncs_after_checkout,
    test_prepare_workspace_non_sentinel_passes_through,
    test_prepare_workspace_update_fails,
)

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

__all__ = [
    "test_all_steps_hidden_all_hidden",
    "test_all_steps_hidden_empty_steps",
    "test_all_steps_hidden_missing_file",
    "test_all_steps_hidden_mixed",
    "test_all_steps_hidden_no_hidden_key",
    "test_all_steps_hidden_skipped_steps_ignored",
    "test_all_steps_hidden_visible_completed_step",
    "test_clear_agent_meta_tribe_removes_canonical_and_legacy_keys",
    "test_clear_agent_meta_tribe_safe_noops",
    "test_clear_stale_git_index_lock_keeps_fresh_lock",
    "test_clear_stale_git_index_lock_no_lock_is_noop",
    "test_clear_stale_git_index_lock_removes_abandoned_lock",
    "test_detect_write_and_persist_review_agent_meta",
    "test_finalize_axe_runner_handles_errors",
    "test_finalize_axe_runner_no_matching_patch",
    "test_finalize_axe_runner_success",
    "test_no_proposal_summary_prefers_generic_finalizer_result",
    "test_no_proposal_summary_reads_historical_commit_result_only",
    "test_prepare_workspace_clean_fails",
    "test_prepare_workspace_clears_stale_lock_before_clean",
    "test_prepare_workspace_default_parent_sync_failure_fails",
    "test_prepare_workspace_default_parent_sync_not_implemented_passes",
    "test_prepare_workspace_default_parent_syncs_after_checkout",
    "test_prepare_workspace_non_sentinel_passes_through",
    "test_prepare_workspace_update_fails",
    "test_reset_killed_clears_timestamp",
    "test_sigterm_handler_can_be_rearmed",
    "test_sigterm_handler_contains_logging_failure",
    "test_sigterm_handler_hard_mode_exits_once",
    "test_sigterm_handler_ignores_nested_delivery",
    "test_sigterm_handler_repeated_delivery_is_a_noop",
    "test_sigterm_handler_runs_cleanup_callback",
    "test_sigterm_handler_sets_killed",
    "test_sigterm_handler_subprocess_survives_signal_burst",
    "test_sigterm_handler_writes_without_buffered_stderr",
    "test_write_done_marker_can_write_visible_review_agent",
]
