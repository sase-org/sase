"""Tests for the deferred, coalesced bead-confirmation warmup.

Row and header rendering can only show bead UI from a warm confirmation cache,
so ``AgentBeadWarmupMixin`` confirms visible bead candidates off the
startup-critical loader path: a coalesced background worker resolves the
uncached or expired candidates among the visible rows after a load applies,
then patches rows whose confirmed state changed in place by identity.

Split facade: the tests now live in
``test_agents_bead_warmup_schedule``, ``test_agents_bead_warmup_results``,
and ``test_agents_bead_warmup_run``. This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agents_bead_warmup_results import (
    test_apply_noop_without_results,
    test_apply_patches_only_result_rows,
    test_apply_patches_rows_losing_confirmed_bead,
    test_apply_rematches_current_object_by_identity,
    test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph,
    test_apply_wait_bead_status_results_passes_fresh_count_override,
    test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure,
    test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key,
    test_warm_confirmed_bead_displays_omits_missing_and_non_candidates,
    test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation,
    test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate,
    test_warm_confirmed_bead_displays_reuses_store_for_batch,
)
from tests.ace.tui.test_agents_bead_warmup_run import (
    WarmupProbe,
    test_forced_stranded_warmup_failure_keeps_project_and_retries,
    test_pending_request_runs_followup_scan_with_positive_timer_delay,
    test_run_confirms_applies_and_clears_running,
    test_run_defers_behind_navigation_gate,
    test_run_missing_candidate_stays_silent,
    test_run_noop_without_candidates,
    test_run_suppresses_pending_when_caches_are_fresh,
    test_warmup_does_not_block_textual_message_pump,
)
from tests.ace.tui.test_agents_bead_warmup_schedule import (
    test_schedule_collapses_to_one_detached_worker,
    test_schedule_marks_pending_while_running,
    test_schedule_noop_before_first_load,
    test_schedule_skips_empty_candidate_scan,
    test_schedule_spawns_worker_after_first_load,
    test_warmup_candidates_bound_historical_waiters_and_stranded_projects,
    test_warmup_candidates_include_expired_cached_bead_candidates,
    test_warmup_candidates_include_stale_wait_bead_statuses,
    test_warmup_candidates_only_uncached_bead_candidates,
)

__test__ = False

__all__ = [
    "WarmupProbe",
    "test_apply_noop_without_results",
    "test_apply_patches_only_result_rows",
    "test_apply_patches_rows_losing_confirmed_bead",
    "test_apply_rematches_current_object_by_identity",
    "test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph",
    "test_apply_wait_bead_status_results_passes_fresh_count_override",
    "test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure",
    "test_forced_stranded_warmup_failure_keeps_project_and_retries",
    "test_pending_request_runs_followup_scan_with_positive_timer_delay",
    "test_run_confirms_applies_and_clears_running",
    "test_run_defers_behind_navigation_gate",
    "test_run_missing_candidate_stays_silent",
    "test_run_noop_without_candidates",
    "test_run_suppresses_pending_when_caches_are_fresh",
    "test_schedule_collapses_to_one_detached_worker",
    "test_schedule_marks_pending_while_running",
    "test_schedule_noop_before_first_load",
    "test_schedule_skips_empty_candidate_scan",
    "test_schedule_spawns_worker_after_first_load",
    "test_warmup_candidates_bound_historical_waiters_and_stranded_projects",
    "test_warmup_candidates_include_expired_cached_bead_candidates",
    "test_warmup_candidates_include_stale_wait_bead_statuses",
    "test_warmup_candidates_only_uncached_bead_candidates",
    "test_warmup_does_not_block_textual_message_pump",
    "test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key",
    "test_warm_confirmed_bead_displays_omits_missing_and_non_candidates",
    "test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation",
    "test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate",
    "test_warm_confirmed_bead_displays_reuses_store_for_batch",
]
