"""Owner-aware snapshot tests for the Node Finder row model.

Split facade: the tests now live in ``test_node_finder_snapshot_hidden``,
``test_node_finder_snapshot_workflow``,
``test_node_finder_snapshot_counts``,
``test_node_finder_snapshot_facets``, and
``test_node_finder_snapshot_describe``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui._node_finder_snapshot_shared import NodeFinderHarness
from tests.ace.tui.test_node_finder_snapshot_counts import (
    test_fused_facets_keep_counts_ancestors_and_reasons_across_grouping_modes,
    test_snapshot_header_counts_match_brute_force_with_mixed_hidden_reasons,
)
from tests.ace.tui.test_node_finder_snapshot_describe import (
    test_batched_description_matches_single_row,
    test_plain_row_describer_matches_single_row,
)
from tests.ace.tui.test_node_finder_snapshot_facets import (
    test_fold_filter_facets_match_direct_reads,
    test_panel_tree_state_matches_rebuild,
)
from tests.ace.tui.test_node_finder_snapshot_hidden import (
    test_collapsed_banner_hides_without_fold_reasons,
    test_collapsed_clan_member_is_fold_hidden,
    test_collapsed_panel_marks_rows,
    test_collapsed_session_turns_name_the_session,
    test_folded_and_query_hidden_at_once,
    test_i_hidden_rows_use_the_pre_hide_roster_and_keep_tree_position,
    test_i_hidden_snapshot_omits_dismissed_and_explicitly_removed_rows,
    test_query_hidden_on_both_flag_branches,
    test_remote_fleet_row_is_listed,
    test_visible_row_carries_here_and_no_reasons,
)
from tests.ace.tui.test_node_finder_snapshot_workflow import (
    test_identities_unique_and_expanded_order_matches_tab,
    test_non_agent_steps_are_context_only_or_omitted,
    test_snapshot_filter_hints_map_to_identities,
    test_starting_dismissed_and_hidden_only_parents_omitted,
    test_synthetic_unknown_step_kind_is_excluded,
)

__test__ = False

__all__ = [
    "NodeFinderHarness",
    "test_batched_description_matches_single_row",
    "test_collapsed_banner_hides_without_fold_reasons",
    "test_collapsed_clan_member_is_fold_hidden",
    "test_collapsed_panel_marks_rows",
    "test_collapsed_session_turns_name_the_session",
    "test_fold_filter_facets_match_direct_reads",
    "test_folded_and_query_hidden_at_once",
    "test_fused_facets_keep_counts_ancestors_and_reasons_across_grouping_modes",
    "test_i_hidden_rows_use_the_pre_hide_roster_and_keep_tree_position",
    "test_i_hidden_snapshot_omits_dismissed_and_explicitly_removed_rows",
    "test_identities_unique_and_expanded_order_matches_tab",
    "test_non_agent_steps_are_context_only_or_omitted",
    "test_panel_tree_state_matches_rebuild",
    "test_plain_row_describer_matches_single_row",
    "test_query_hidden_on_both_flag_branches",
    "test_remote_fleet_row_is_listed",
    "test_snapshot_filter_hints_map_to_identities",
    "test_snapshot_header_counts_match_brute_force_with_mixed_hidden_reasons",
    "test_starting_dismissed_and_hidden_only_parents_omitted",
    "test_synthetic_unknown_step_kind_is_excluded",
    "test_visible_row_carries_here_and_no_reasons",
]
