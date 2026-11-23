"""Compatibility facade for exact-delta copy-on-write tests.

The tests live in focused modules while their original import path remains
available here.
"""

from __future__ import annotations

from tests.test_agents_tab_delta_copy_fast_path_eligibility import (
    test_fast_path_eligible_for_artifact_delta_patch,
    test_fast_path_fallback_reasons,
    test_scalar_vs_relationship_keys_documented,
    test_delta_isolated_copy_detaches_mutable_containers,
    test_incomplete_history_snapshot_is_eligible,
)
from tests.test_agents_tab_delta_copy_fast_path_preparation import (
    test_scalar_delta_equivalence_fast_vs_fallback,
    test_fast_path_uses_no_deep_copies_for_small_delta,
    test_fast_path_without_complete_watermark_uses_no_deep_copies,
    test_exact_delta_deletion_equivalence,
    test_child_add_remove_equivalence,
)
from tests.test_agents_tab_delta_copy_fast_path_sharing import (
    test_terminal_transition_shares_unrelated_rows,
    test_clan_share_back_is_alias_closed,
    test_agent_session_child_change_keeps_one_published_graph,
    test_child_graph_changes_keep_one_published_graph,
    test_unrelated_delta_preserves_live_identity,
    test_unchanged_referrer_does_not_keep_a_stale_live_reference,
    test_share_back_comparisons_run_once_per_row_on_worker,
    test_share_back_comparison_exception_leaves_live_rows_untouched,
    test_share_back_boundary_shares_unchanged_rows,
    test_named_proc_rows_keep_aliases_consistent,
    test_fleet_rows_stay_owned_and_shared,
)

__test__ = False

__all__ = (
    "test_agent_session_child_change_keeps_one_published_graph",
    "test_child_add_remove_equivalence",
    "test_child_graph_changes_keep_one_published_graph",
    "test_clan_share_back_is_alias_closed",
    "test_delta_isolated_copy_detaches_mutable_containers",
    "test_exact_delta_deletion_equivalence",
    "test_fast_path_eligible_for_artifact_delta_patch",
    "test_fast_path_fallback_reasons",
    "test_fast_path_uses_no_deep_copies_for_small_delta",
    "test_fast_path_without_complete_watermark_uses_no_deep_copies",
    "test_fleet_rows_stay_owned_and_shared",
    "test_incomplete_history_snapshot_is_eligible",
    "test_named_proc_rows_keep_aliases_consistent",
    "test_scalar_delta_equivalence_fast_vs_fallback",
    "test_scalar_vs_relationship_keys_documented",
    "test_share_back_boundary_shares_unchanged_rows",
    "test_share_back_comparison_exception_leaves_live_rows_untouched",
    "test_share_back_comparisons_run_once_per_row_on_worker",
    "test_terminal_transition_shares_unrelated_rows",
    "test_unchanged_referrer_does_not_keep_a_stale_live_reference",
    "test_unrelated_delta_preserves_live_identity",
)
