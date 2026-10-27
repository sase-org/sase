"""Waiter alerts for strands whose bead work has ended without closing.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_axe_chop_wait_checks_stranded_beads_notify import (
    test_collector_failure_leaves_waiter_parked_and_notifications_unchanged,
    test_open_child_plan_suppresses_stranded_wait_alert,
    test_pending_monitor_or_gate_handoff_suppresses_stranded_wait_alert,
    test_stranded_alert_dismisses_when_waiter_died,
    test_stranded_alert_dismisses_when_waiter_is_already_ready,
    test_stranded_alert_dismisses_when_waiting_marker_is_removed,
    test_stranded_bead_notification_dismisses_after_close,
    test_stranded_bead_waiters_share_one_notification,
    test_task_stranded_bead_notification_has_task_relaunch_command,
    test_wait_checks_does_not_notify_before_stranding,
)
from tests.test_axe_chop_wait_checks_stranded_beads_reconcile import (
    test_closed_bead_absent_from_reducer_still_dismisses_outstanding_alert,
    test_collection_failure_retains_outstanding_stranded_alert,
    test_no_stranded_work_without_pending_waits_or_active_alerts,
    test_notification_only_reconciliation_dismisses_resolved_states,
    test_parse_stranded_bead_wait_dedup_key_ignores_malformed,
    test_reconciliation_collects_only_pending_and_outstanding_ids,
    test_status_read_failure_retains_outstanding_stranded_alert,
    test_targeted_collector_loads_only_named_candidates_and_child_context,
    test_targeted_report_cache_is_shared_across_ticks_and_invalidates,
)

__test__ = False

__all__ = [
    "test_closed_bead_absent_from_reducer_still_dismisses_outstanding_alert",
    "test_collection_failure_retains_outstanding_stranded_alert",
    "test_collector_failure_leaves_waiter_parked_and_notifications_unchanged",
    "test_no_stranded_work_without_pending_waits_or_active_alerts",
    "test_notification_only_reconciliation_dismisses_resolved_states",
    "test_open_child_plan_suppresses_stranded_wait_alert",
    "test_parse_stranded_bead_wait_dedup_key_ignores_malformed",
    "test_pending_monitor_or_gate_handoff_suppresses_stranded_wait_alert",
    "test_reconciliation_collects_only_pending_and_outstanding_ids",
    "test_status_read_failure_retains_outstanding_stranded_alert",
    "test_stranded_alert_dismisses_when_waiter_died",
    "test_stranded_alert_dismisses_when_waiter_is_already_ready",
    "test_stranded_alert_dismisses_when_waiting_marker_is_removed",
    "test_stranded_bead_notification_dismisses_after_close",
    "test_stranded_bead_waiters_share_one_notification",
    "test_targeted_collector_loads_only_named_candidates_and_child_context",
    "test_targeted_report_cache_is_shared_across_ticks_and_invalidates",
    "test_task_stranded_bead_notification_has_task_relaunch_command",
    "test_wait_checks_does_not_notify_before_stranding",
]
