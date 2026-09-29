"""Tests for the per-agent bead-touch loader and merge (bead sase-14j.4).

Split facade: the tests now live in ``test_agent_bead_touches_merge``,
``test_agent_bead_touches_loader``, and ``test_agent_bead_touches_wiring``
(shared helpers in ``_agent_bead_touches_helpers``). This module re-exports
the public names so the original import path keeps working. It collects no
tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_agent_bead_touches_loader import (
    test_agent_session_loader_attributes_touches_with_role_labels,
    test_loader_caches_snapshot_across_agents,
    test_loader_caps_at_max_kept_touches,
    test_loader_filters_to_agent_by_local_and_globalized_name,
    test_loader_respects_limit,
    test_loader_returns_empty_when_project_unresolvable,
    test_loader_returns_empty_when_query_fails,
    test_loader_throttles_reread_then_refreshes_on_change,
    test_single_member_agent_session_takes_per_agent_path,
)
from tests.ace.tui.widgets.test_agent_bead_touches_merge import (
    test_canonical_bead_id_stays_exact_after_prefix,
    test_canonical_bead_id_strips_prefix_and_whitespace,
    test_merge_carries_creation_reason_from_creator_row_only,
    test_merge_carries_newest_read_reason_first,
    test_merge_counts_repeated_reads_and_read_only_beads,
    test_merge_deduplicates_a_repeated_note_preview_id,
    test_merge_empty_inputs_returns_empty,
    test_merge_entry_type_defaults,
    test_merge_folds_bead_read_into_touch_row,
    test_merge_ignores_non_bead_refs,
    test_merge_keeps_shared_agent_session_label,
    test_merge_leaves_assigned_only_row_without_creation_reason,
    test_merge_marks_own_beads_including_untouched,
    test_merge_never_infers_creation_from_assignment,
    test_merge_own_ids_match_after_canonicalization,
    test_merge_prefers_standing_close_then_newest,
    test_merge_ranks_newest_touch_first_with_id_tiebreak,
    test_merge_selects_newest_note_across_session_members_with_its_role,
    test_merge_single_touch_carries_verbs_title_and_timestamps,
    test_merge_sums_verbs_across_agent_session_producers,
    test_merge_skips_touches_without_a_bead_id,
    test_merge_takes_first_available_title,
    test_merge_titles_assigned_only_row_from_resolved_summaries,
    test_own_bead_ids_collects_phase_epic_and_derived,
    test_own_bead_ids_dedupes_and_skips_blanks,
    test_own_bead_ids_derives_from_bead_work_name,
    test_own_bead_ids_empty_for_ordinary_agent,
)
from tests.ace.tui.widgets.test_agent_bead_touches_wiring import (
    test_artifacts_lane_empty_index_resolves_empty_view,
    test_artifacts_lane_resolves_merged_bead_touch_entries,
    test_cache_merge_keeps_bead_view_when_other_lane_rebuilds,
    test_non_artifacts_lane_leaves_bead_view_unresolved,
)

__test__ = False

__all__ = [
    "test_agent_session_loader_attributes_touches_with_role_labels",
    "test_artifacts_lane_empty_index_resolves_empty_view",
    "test_artifacts_lane_resolves_merged_bead_touch_entries",
    "test_cache_merge_keeps_bead_view_when_other_lane_rebuilds",
    "test_canonical_bead_id_stays_exact_after_prefix",
    "test_canonical_bead_id_strips_prefix_and_whitespace",
    "test_loader_caches_snapshot_across_agents",
    "test_loader_caps_at_max_kept_touches",
    "test_loader_filters_to_agent_by_local_and_globalized_name",
    "test_loader_respects_limit",
    "test_loader_returns_empty_when_project_unresolvable",
    "test_loader_returns_empty_when_query_fails",
    "test_loader_throttles_reread_then_refreshes_on_change",
    "test_merge_carries_creation_reason_from_creator_row_only",
    "test_merge_carries_newest_read_reason_first",
    "test_merge_counts_repeated_reads_and_read_only_beads",
    "test_merge_deduplicates_a_repeated_note_preview_id",
    "test_merge_empty_inputs_returns_empty",
    "test_merge_entry_type_defaults",
    "test_merge_folds_bead_read_into_touch_row",
    "test_merge_ignores_non_bead_refs",
    "test_merge_keeps_shared_agent_session_label",
    "test_merge_leaves_assigned_only_row_without_creation_reason",
    "test_merge_marks_own_beads_including_untouched",
    "test_merge_never_infers_creation_from_assignment",
    "test_merge_own_ids_match_after_canonicalization",
    "test_merge_prefers_standing_close_then_newest",
    "test_merge_ranks_newest_touch_first_with_id_tiebreak",
    "test_merge_selects_newest_note_across_session_members_with_its_role",
    "test_merge_single_touch_carries_verbs_title_and_timestamps",
    "test_merge_sums_verbs_across_agent_session_producers",
    "test_merge_skips_touches_without_a_bead_id",
    "test_merge_takes_first_available_title",
    "test_merge_titles_assigned_only_row_from_resolved_summaries",
    "test_non_artifacts_lane_leaves_bead_view_unresolved",
    "test_own_bead_ids_collects_phase_epic_and_derived",
    "test_own_bead_ids_dedupes_and_skips_blanks",
    "test_own_bead_ids_derives_from_bead_work_name",
    "test_own_bead_ids_empty_for_ordinary_agent",
    "test_single_member_agent_session_takes_per_agent_path",
]
