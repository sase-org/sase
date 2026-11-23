"""Off-thread compute and in-place apply coverage for bead warmup.

Split facade: the tests now live in
``test_agents_bead_warmup_results_apply``,
``test_agents_bead_warmup_results_displays``, and
``test_agents_bead_warmup_results_fingerprint``. This module re-exports the
public names so the original import path keeps working. It collects no tests
itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agents_bead_warmup_results_apply import (
    test_apply_noop_without_results,
    test_apply_patches_only_result_rows,
    test_apply_patches_rows_losing_confirmed_bead,
    test_apply_rematches_current_object_by_identity,
    test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph,
    test_apply_wait_bead_status_results_passes_fresh_count_override,
    test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure,
)
from tests.ace.tui.test_agents_bead_warmup_results_displays import (
    test_warm_confirmed_bead_displays_clears_fingerprint_with_entries,
    test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key,
    test_warm_confirmed_bead_displays_missing_fingerprint_fails_open,
    test_warm_confirmed_bead_displays_omits_missing_and_non_candidates,
    test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation,
    test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate,
    test_warm_confirmed_bead_displays_reports_deleted_when_store_changes,
    test_warm_confirmed_bead_displays_rereads_missing_when_store_changes,
    test_warm_confirmed_bead_displays_rereads_when_store_changes,
    test_warm_confirmed_bead_displays_reuses_store_for_batch,
    test_warm_confirmed_bead_displays_reuses_unchanged_store_across_ttl,
    test_warm_confirmed_bead_displays_reuses_unchanged_store_for_missing,
    test_warm_confirmed_bead_displays_skips_unrelated_lineage_changes,
    test_warm_confirmed_bead_displays_unknown_fingerprint_fails_open,
)
from tests.ace.tui.test_agents_bead_warmup_results_fingerprint import (
    test_bead_display_fingerprint_ignores_other_event_lineages,
    test_bead_display_fingerprint_tracks_candidate_lineage_creation,
    test_bead_display_fingerprint_tracks_legacy_store_changes,
)

__test__ = False

__all__ = [
    "test_apply_noop_without_results",
    "test_apply_patches_only_result_rows",
    "test_apply_patches_rows_losing_confirmed_bead",
    "test_apply_rematches_current_object_by_identity",
    "test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph",
    "test_apply_wait_bead_status_results_passes_fresh_count_override",
    "test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure",
    "test_bead_display_fingerprint_ignores_other_event_lineages",
    "test_bead_display_fingerprint_tracks_candidate_lineage_creation",
    "test_bead_display_fingerprint_tracks_legacy_store_changes",
    "test_warm_confirmed_bead_displays_clears_fingerprint_with_entries",
    "test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key",
    "test_warm_confirmed_bead_displays_missing_fingerprint_fails_open",
    "test_warm_confirmed_bead_displays_omits_missing_and_non_candidates",
    "test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation",
    "test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate",
    "test_warm_confirmed_bead_displays_reports_deleted_when_store_changes",
    "test_warm_confirmed_bead_displays_rereads_missing_when_store_changes",
    "test_warm_confirmed_bead_displays_rereads_when_store_changes",
    "test_warm_confirmed_bead_displays_reuses_store_for_batch",
    "test_warm_confirmed_bead_displays_reuses_unchanged_store_across_ttl",
    "test_warm_confirmed_bead_displays_reuses_unchanged_store_for_missing",
    "test_warm_confirmed_bead_displays_skips_unrelated_lineage_changes",
    "test_warm_confirmed_bead_displays_unknown_fingerprint_fails_open",
]
