"""Public import facade for the split Artifacts Beads filtering tests."""

from __future__ import annotations

# Keep imports from this historical module path available without collecting the
# re-exported tests a second time.
__test__ = False

from tests.ace.tui.test_artifacts_beads_filtering_queries import (
    test_running_agent_predicate_requires_assigned_active_bead,
    test_parse_bead_filter_query_accepts_negated_repeatable_terms,
    test_invalid_bead_filter_tokens_are_rejected,
    test_filter_terms_match_bead_metadata_and_derived_labels,
    test_task_type_filter_matches_stored_slug,
    test_due_filter_matches_precomputed_flag_state,
    test_type_flag_filter_matches_flag_task_beads,
    test_has_plus_one_and_evidence_text_use_cached_filter_index,
    test_external_issue_filters_match_refs_states_and_labels,
    test_has_reopened_and_close_history_text_use_cached_filter_index,
    test_default_hide_closed_filter_hides_closed_phases_and_shows_counts,
    test_filter_index_reuses_unchanged_snapshot_source_key,
)

from tests.ace.tui.test_artifacts_beads_filtering_ui import (
    test_bead_filter_bar_completes_negated_status_and_dynamic_people,
    test_hide_closed_default_is_visible_and_clearable,
    test_clicking_idle_bead_bar_opens_the_filter_session,
    test_committing_bead_query_updates_idle_bar,
    test_changing_project_scope_keeps_idle_bead_bar_in_sync,
    test_bead_bar_geometry_is_unchanged_between_idle_and_editing,
)

from tests.ace.tui.test_artifacts_beads_filtering_stranded import (
    test_status_stranded_filter_matches_cached_stranded_leaves,
    test_status_stranded_index_key_follows_report_replacement,
)

__all__ = [
    "test_running_agent_predicate_requires_assigned_active_bead",
    "test_parse_bead_filter_query_accepts_negated_repeatable_terms",
    "test_invalid_bead_filter_tokens_are_rejected",
    "test_filter_terms_match_bead_metadata_and_derived_labels",
    "test_task_type_filter_matches_stored_slug",
    "test_due_filter_matches_precomputed_flag_state",
    "test_type_flag_filter_matches_flag_task_beads",
    "test_has_plus_one_and_evidence_text_use_cached_filter_index",
    "test_external_issue_filters_match_refs_states_and_labels",
    "test_has_reopened_and_close_history_text_use_cached_filter_index",
    "test_default_hide_closed_filter_hides_closed_phases_and_shows_counts",
    "test_filter_index_reuses_unchanged_snapshot_source_key",
    "test_bead_filter_bar_completes_negated_status_and_dynamic_people",
    "test_hide_closed_default_is_visible_and_clearable",
    "test_clicking_idle_bead_bar_opens_the_filter_session",
    "test_committing_bead_query_updates_idle_bar",
    "test_changing_project_scope_keeps_idle_bead_bar_in_sync",
    "test_bead_bar_geometry_is_unchanged_between_idle_and_editing",
    "test_status_stranded_filter_matches_cached_stranded_leaves",
    "test_status_stranded_index_key_follows_report_replacement",
]
