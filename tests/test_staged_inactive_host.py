"""Failed-origin inactive settlement: host wiring end to end.

Covers the ``inactive-stage-host`` phase: the Rust inactive-stage policy
reaches the stranded collector, admission, lane, owner, and reconciler
paths; a never-started monitor stage settles idempotently once its origin
has failed; and later turns are no longer blocked by the dead stage while
every recovery record survives.

The test implementations live in private modules to keep this compatibility
import path small while preserving pytest collection and public test names.
"""

from __future__ import annotations

from tests._test_staged_inactive_host_owner import (
    test_failed_origin_releases_lane_and_pending_owner,
    test_fresh_turn_stages_questions_after_settlement,
    test_incomplete_cleanup_stays_retryable,
    test_later_turn_questions_use_fresh_artifacts_after_settlement,
    test_live_origin_monitor_blocks_lane_and_holds_owner,
    test_mismatched_owner_index_is_not_deleted,
    test_premature_marker_does_not_skip_unfinished_cleanup,
    test_running_member_cleanup_stays_incomplete,
    test_settlement_removes_pending_owner_row_and_keeps_lane_clear,
    test_unreadable_owner_index_blocks_settlement,
)
from tests._test_staged_inactive_host_reconcile import (
    test_busy_adoption_lock_skips_settlement_without_blocking,
    test_finalize_failed_turn_settles_without_periodic_sweep,
    test_finalize_successful_turn_does_not_settle,
    test_malformed_stage_never_settles,
    test_maybe_settle_waits_for_failed_done_marker,
    test_reconcile_settles_failed_origin_and_stays_quiet,
)
from tests._test_staged_inactive_host_recovery import (
    test_readopt_invalidates_settlement_exactly_once,
    test_settlement_releases_staged_join_reservation,
    test_settlement_settles_reserved_tool_run_as_never_executed,
)
from tests._test_staged_inactive_host_settlement import (
    test_adopted_stage_never_settles,
    test_live_origin_still_refuses_second_handoff,
    test_replacement_stage_is_not_suppressed_by_old_settlement,
    test_settled_origin_refuses_same_turn_questions_overwrite,
    test_settled_origin_releases_admission_slot,
    test_settlement_is_idempotent_and_keeps_recovery_evidence,
    test_settlement_requires_failed_terminal_evidence,
    test_submitted_proc_blocks_settlement,
    test_unreadable_proc_store_blocks_settlement,
)
from tests._test_staged_inactive_host_stranded import (
    test_failed_origin_monitor_stage_reports_origin_failed,
    test_failed_origin_strands_and_blocks_waiting_ancestor,
    test_live_origin_keeps_pending_handoff_ownership,
    test_member_order_does_not_change_stranded_verdict,
    test_receipt_only_failed_origin_is_inactive_but_not_eligible,
    test_running_origin_without_terminal_marker_stays_pending,
    test_started_monitor_stays_process_live,
    test_unstarted_monitor_is_not_process_live,
)

__all__ = [
    "test_adopted_stage_never_settles",
    "test_busy_adoption_lock_skips_settlement_without_blocking",
    "test_failed_origin_monitor_stage_reports_origin_failed",
    "test_failed_origin_releases_lane_and_pending_owner",
    "test_failed_origin_strands_and_blocks_waiting_ancestor",
    "test_finalize_failed_turn_settles_without_periodic_sweep",
    "test_finalize_successful_turn_does_not_settle",
    "test_fresh_turn_stages_questions_after_settlement",
    "test_incomplete_cleanup_stays_retryable",
    "test_later_turn_questions_use_fresh_artifacts_after_settlement",
    "test_live_origin_keeps_pending_handoff_ownership",
    "test_live_origin_monitor_blocks_lane_and_holds_owner",
    "test_live_origin_still_refuses_second_handoff",
    "test_malformed_stage_never_settles",
    "test_maybe_settle_waits_for_failed_done_marker",
    "test_member_order_does_not_change_stranded_verdict",
    "test_mismatched_owner_index_is_not_deleted",
    "test_premature_marker_does_not_skip_unfinished_cleanup",
    "test_readopt_invalidates_settlement_exactly_once",
    "test_receipt_only_failed_origin_is_inactive_but_not_eligible",
    "test_reconcile_settles_failed_origin_and_stays_quiet",
    "test_replacement_stage_is_not_suppressed_by_old_settlement",
    "test_running_member_cleanup_stays_incomplete",
    "test_running_origin_without_terminal_marker_stays_pending",
    "test_settled_origin_refuses_same_turn_questions_overwrite",
    "test_settled_origin_releases_admission_slot",
    "test_settlement_is_idempotent_and_keeps_recovery_evidence",
    "test_settlement_releases_staged_join_reservation",
    "test_settlement_removes_pending_owner_row_and_keeps_lane_clear",
    "test_settlement_requires_failed_terminal_evidence",
    "test_settlement_settles_reserved_tool_run_as_never_executed",
    "test_started_monitor_stays_process_live",
    "test_submitted_proc_blocks_settlement",
    "test_unreadable_owner_index_blocks_settlement",
    "test_unreadable_proc_store_blocks_settlement",
    "test_unstarted_monitor_is_not_process_live",
]
