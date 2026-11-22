"""Tests for the TUI's authoritative machine-capacity report feed.

The test bodies live in private modules; these imports preserve the original
pytest collection and import path.
"""

from __future__ import annotations

from tests.ace.tui._machine_capacity_report_feed_authoritative_tests import (
    test_authoritative_report_drives_header_and_waiter_context_without_roster,
    test_each_roster_apply_uses_the_latest_report_and_keeps_an_estimate_witness,
    test_report_refresh_copies_queue_context_to_live_rows_and_patches_them,
)
from tests.ace.tui._machine_capacity_report_feed_lifecycle_tests import (
    test_drift_telemetry_waits_for_two_distinct_comparisons,
    test_feed_moves_from_roster_estimate_to_authoritative_report,
    test_feed_tasks_cancel_at_teardown,
    test_feed_tick_stats_nothing_on_the_ui_thread,
    test_refresh_task_rebuilds_when_token_changes,
    test_refresh_task_skips_build_when_token_unchanged,
    test_token_change_during_compute_coalesces_to_one_trailing_report,
)
from tests.ace.tui._machine_capacity_report_feed_revalidation_tests import (
    test_changed_inspector_fields_install_when_rebuilt,
    test_hold_expiry_without_token_change_rebuilds,
    test_inspector_open_forces_install_on_unchanged_visible,
    test_override_expiry_without_token_change_rebuilds_and_installs,
    test_process_death_without_token_change_rebuilds_and_installs,
    test_token_change_rebuilds_but_skips_unchanged_install,
    test_token_probe_failure_fails_open_to_rebuild,
    test_unchanged_across_many_ten_second_boundaries_skips_rebuilds,
)

__all__ = [
    "test_authoritative_report_drives_header_and_waiter_context_without_roster",
    "test_changed_inspector_fields_install_when_rebuilt",
    "test_drift_telemetry_waits_for_two_distinct_comparisons",
    "test_each_roster_apply_uses_the_latest_report_and_keeps_an_estimate_witness",
    "test_feed_moves_from_roster_estimate_to_authoritative_report",
    "test_feed_tasks_cancel_at_teardown",
    "test_feed_tick_stats_nothing_on_the_ui_thread",
    "test_hold_expiry_without_token_change_rebuilds",
    "test_inspector_open_forces_install_on_unchanged_visible",
    "test_override_expiry_without_token_change_rebuilds_and_installs",
    "test_process_death_without_token_change_rebuilds_and_installs",
    "test_refresh_task_rebuilds_when_token_changes",
    "test_refresh_task_skips_build_when_token_unchanged",
    "test_report_refresh_copies_queue_context_to_live_rows_and_patches_them",
    "test_token_change_during_compute_coalesces_to_one_trailing_report",
    "test_token_change_rebuilds_but_skips_unchanged_install",
    "test_token_probe_failure_fails_open_to_rebuild",
    "test_unchanged_across_many_ten_second_boundaries_skips_rebuilds",
]
