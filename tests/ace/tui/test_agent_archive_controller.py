"""Corpus-controller tests: generations, prewarm gate, idle ticks, failures.

Blocked workers and injected probes prove last-request-wins rejection,
cancellation, warm-handle reuse, no compile before the Inbox gate, no
catalog scan on quiet ticks, and an unaffected Inbox when the index is
missing or unreadable.

Split facade: the tests now live in ``test_agent_archive_controller_prewarm``,
``test_agent_archive_controller_generations``, and
``test_agent_archive_controller_lookup``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agent_archive_controller_generations import (
    test_cancel_drops_blocked_worker,
    test_init_controller_is_cold,
    test_input_drift_rebuilds_and_keeps_selection,
    test_link_signature_drift_reloads_facets,
    test_missing_index_is_honest_and_leaves_inbox_alone,
    test_probe_error_publishes_unavailable_and_unwedges_idle,
    test_query_reuses_warm_handle_without_facet_reload,
    test_rebuilding_index_serves_rows_and_progress,
    test_stale_generation_is_dropped,
    test_unreadable_index_publishes_rebuild_hint,
    test_worker_publishes_display_snapshot_for_project_banners,
)
from tests.ace.tui.test_agent_archive_controller_lookup import (
    test_adjacent_selection_fallback,
    test_coalesced_idle_does_not_publish_false_missing_for_queued_open,
    test_idle_with_pending_exact_name_does_not_short_circuit_unchanged,
    test_lookup_miss_clears_pending_and_publishes_missing,
    test_lookup_owner_of_workflow_child_is_typed,
    test_lookup_reads_name_from_request_snapshot_not_live_state,
    test_open_with_query_lookup_selects_row,
    test_overlapping_idle_rebuilds_coalesce_to_one_in_flight,
    test_queued_explicit_open_drains_on_idle_tick,
)
from tests.ace.tui.test_agent_archive_controller_prewarm import (
    test_bounded_inbox_load_does_not_open_prewarm_gate,
    test_complete_idle_prewarms_once_and_idle_tick_skips_compile,
    test_early_open_paints_loading_and_queues_until_gate,
    test_flag_off_never_probes_or_prewarms,
    test_inbox_load_scheduled_resets_on_apply_and_failure,
    test_prewarm_waits_for_idle_ui,
    test_prompt_typing_defers_idle_requery,
)

__test__ = False

__all__ = [
    "test_adjacent_selection_fallback",
    "test_bounded_inbox_load_does_not_open_prewarm_gate",
    "test_cancel_drops_blocked_worker",
    "test_coalesced_idle_does_not_publish_false_missing_for_queued_open",
    "test_complete_idle_prewarms_once_and_idle_tick_skips_compile",
    "test_early_open_paints_loading_and_queues_until_gate",
    "test_flag_off_never_probes_or_prewarms",
    "test_idle_with_pending_exact_name_does_not_short_circuit_unchanged",
    "test_inbox_load_scheduled_resets_on_apply_and_failure",
    "test_init_controller_is_cold",
    "test_input_drift_rebuilds_and_keeps_selection",
    "test_link_signature_drift_reloads_facets",
    "test_lookup_miss_clears_pending_and_publishes_missing",
    "test_lookup_owner_of_workflow_child_is_typed",
    "test_lookup_reads_name_from_request_snapshot_not_live_state",
    "test_missing_index_is_honest_and_leaves_inbox_alone",
    "test_open_with_query_lookup_selects_row",
    "test_overlapping_idle_rebuilds_coalesce_to_one_in_flight",
    "test_prewarm_waits_for_idle_ui",
    "test_probe_error_publishes_unavailable_and_unwedges_idle",
    "test_prompt_typing_defers_idle_requery",
    "test_query_reuses_warm_handle_without_facet_reload",
    "test_queued_explicit_open_drains_on_idle_tick",
    "test_rebuilding_index_serves_rows_and_progress",
    "test_stale_generation_is_dropped",
    "test_unreadable_index_publishes_rebuild_hint",
    "test_worker_publishes_display_snapshot_for_project_banners",
]
