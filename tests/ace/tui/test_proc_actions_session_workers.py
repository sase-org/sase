"""Session-worker concurrency guards in ``ProcActionsMixin``.

Split facade: the tests now live in
``test_proc_actions_session_workers_guards``,
``test_proc_actions_session_workers_overlay``,
``test_proc_actions_session_workers_indicators``, and
``test_proc_actions_session_workers_attempts``. This module re-exports the
public names so the original import path keeps working. It collects no tests
itself.
"""

from __future__ import annotations

from tests.ace.tui.test_proc_actions_session_workers_attempts import (
    test_durable_delivery_skips_settle_for_collisions_and_other_lanes,
    test_durable_plugin_update_delivery_schedules_settle,
    test_non_update_session_worker_never_touches_journal,
    test_session_worker_error_path_settles_failure_off_thread,
    test_update_session_worker_begins_before_body_and_settles_before_complete,
    test_update_session_worker_failure_view_then_success_clears,
)
from tests.ace.tui.test_proc_actions_session_workers_guards import (
    test_durable_scope_blocks_session_worker,
    test_pending_durable_scope_blocks_session_worker,
    test_session_claim_releases_after_completion_and_error,
    test_session_scope_blocks_durable_submit,
    test_session_worker_rejects_duplicate_dedup_key,
    test_session_worker_scope_overlap_rejects_but_disjoint_scope_runs,
    test_session_workers_without_explicit_claims_can_overlap,
)
from tests.ace.tui.test_proc_actions_session_workers_indicators import (
    test_update_proc_indicator_missing_proc_indicator_is_noop,
    test_update_proc_indicator_moves_update_lane_to_green_gear,
    test_update_proc_indicator_splits_ace_and_monitor_counts,
)
from tests.ace.tui.test_proc_actions_session_workers_overlay import (
    test_current_observer_snapshot_replaces_projection,
    test_running_background_procs_excludes_monitor_turns,
    test_session_and_durable_rows_dedup_and_exclude_across_overlay,
    test_session_overlay_never_registers_observer_or_writes_store,
    test_session_overlay_preserves_rows_across_observer_snapshots,
    test_session_overlay_removes_row_after_success_and_error,
    test_session_worker_appears_in_effective_projection_and_counts,
    test_session_worker_logs_error_terminal_record,
    test_session_worker_retains_reporter_output_on_completion,
    test_stale_observer_snapshot_does_not_overwrite_current_projection,
    test_thread_snapshot_delivery_passes_producing_observer,
)

__test__ = False

__all__ = [
    "test_current_observer_snapshot_replaces_projection",
    "test_durable_delivery_skips_settle_for_collisions_and_other_lanes",
    "test_durable_plugin_update_delivery_schedules_settle",
    "test_durable_scope_blocks_session_worker",
    "test_non_update_session_worker_never_touches_journal",
    "test_pending_durable_scope_blocks_session_worker",
    "test_running_background_procs_excludes_monitor_turns",
    "test_session_and_durable_rows_dedup_and_exclude_across_overlay",
    "test_session_claim_releases_after_completion_and_error",
    "test_session_overlay_never_registers_observer_or_writes_store",
    "test_session_overlay_preserves_rows_across_observer_snapshots",
    "test_session_overlay_removes_row_after_success_and_error",
    "test_session_scope_blocks_durable_submit",
    "test_session_worker_appears_in_effective_projection_and_counts",
    "test_session_worker_error_path_settles_failure_off_thread",
    "test_session_worker_logs_error_terminal_record",
    "test_session_worker_rejects_duplicate_dedup_key",
    "test_session_worker_retains_reporter_output_on_completion",
    "test_session_worker_scope_overlap_rejects_but_disjoint_scope_runs",
    "test_session_workers_without_explicit_claims_can_overlap",
    "test_stale_observer_snapshot_does_not_overwrite_current_projection",
    "test_thread_snapshot_delivery_passes_producing_observer",
    "test_update_proc_indicator_missing_proc_indicator_is_noop",
    "test_update_proc_indicator_moves_update_lane_to_green_gear",
    "test_update_proc_indicator_splits_ace_and_monitor_counts",
    "test_update_session_worker_begins_before_body_and_settles_before_complete",
    "test_update_session_worker_failure_view_then_success_clears",
]
