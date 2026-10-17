"""Dispatch and evaluate tests for the release watcher.

Split into focused modules; this module re-exports every public name so the
original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.test_release_watch_decisions_dispatch import (
    test_awaiting_core_skips_floor_ratchet_keeps_full_ci,
    test_dispatch_fresh_red_budget_with_two_old_reds,
    test_first_full_ci_dispatch_and_exact_command,
    test_floor_ratchet_dispatch_and_post_upload_deduplication,
    test_fresh_red_budget_ignores_runs_predating_the_watch,
    test_full_ci_in_flight_status_suppresses_dispatch,
    test_full_ci_red_budget_and_cooldown,
    test_no_dispatch_suppresses_dispatch_but_still_closes,
    test_post_merge_publish_dispatch_is_deduplicated_by_run_creation,
    test_stale_green_full_ci_refresh_requires_unmerged_pr,
)
from tests.test_release_watch_decisions_evaluate import (
    test_all_signal_verdicts,
    test_awaiting_core_suppresses_floor_blocked,
    test_floor_blocked_requires_failed_floor_after_publish_after_core,
    test_master_gate_green_resets_red_clock,
    test_master_gate_in_flight_neither_counts_nor_resets,
    test_master_gate_red_after_budget_without_green,
    test_master_gate_rerun_fires_once_per_sha_for_test_shards_only,
    test_master_gate_sha_change_restarts_red_clock,
    test_prerelease_core_still_awaits,
    test_reached_or_newer_core_restores_floor_blocked,
)
from tests.test_release_watch_decisions_stale import (
    test_current_head_with_red_floor_still_blocked,
    test_no_dispatch_suppresses_pr_refresh,
    test_parse_compare_base_payload,
    test_parse_compare_base_rejects_malformed,
    test_pr_refresh_noop_guard_after_post_dispatch_publish,
    test_stale_head_gives_no_verdict,
    test_stale_head_pr_refresh_once_per_head_sha,
    test_stale_state_line_and_deadline_detail,
)

__test__ = False

__all__ = [
    "test_all_signal_verdicts",
    "test_awaiting_core_skips_floor_ratchet_keeps_full_ci",
    "test_awaiting_core_suppresses_floor_blocked",
    "test_current_head_with_red_floor_still_blocked",
    "test_dispatch_fresh_red_budget_with_two_old_reds",
    "test_first_full_ci_dispatch_and_exact_command",
    "test_floor_blocked_requires_failed_floor_after_publish_after_core",
    "test_floor_ratchet_dispatch_and_post_upload_deduplication",
    "test_fresh_red_budget_ignores_runs_predating_the_watch",
    "test_full_ci_in_flight_status_suppresses_dispatch",
    "test_full_ci_red_budget_and_cooldown",
    "test_master_gate_green_resets_red_clock",
    "test_master_gate_in_flight_neither_counts_nor_resets",
    "test_master_gate_red_after_budget_without_green",
    "test_master_gate_rerun_fires_once_per_sha_for_test_shards_only",
    "test_master_gate_sha_change_restarts_red_clock",
    "test_no_dispatch_suppresses_dispatch_but_still_closes",
    "test_no_dispatch_suppresses_pr_refresh",
    "test_parse_compare_base_payload",
    "test_parse_compare_base_rejects_malformed",
    "test_post_merge_publish_dispatch_is_deduplicated_by_run_creation",
    "test_pr_refresh_noop_guard_after_post_dispatch_publish",
    "test_prerelease_core_still_awaits",
    "test_reached_or_newer_core_restores_floor_blocked",
    "test_stale_green_full_ci_refresh_requires_unmerged_pr",
    "test_stale_head_gives_no_verdict",
    "test_stale_head_pr_refresh_once_per_head_sha",
    "test_stale_state_line_and_deadline_detail",
]
