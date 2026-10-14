"""Tests for the app-owned O(1) link-graph index (bead:sase-ug.5).

Split facade: the tests now live in ``test_link_index_chips``,
``test_link_index_targets``, and ``test_link_index_cache``. This module
re-exports the public names so the original import path keeps working. It
collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_link_index_cache import (
    test_clear_epoch_fences_pending_generation_but_releases_its_caller,
    test_concurrent_requests_for_one_snapshot_compile_once,
    test_distinct_synthetic_snapshots_with_shared_keys_stay_separate,
    test_evicted_scope_keeps_pending_generation_fence,
    test_failed_build_unblocks_waiters_and_retry_succeeds,
    test_requested_chip_cache_is_bounded_and_refills_after_eviction,
)
from tests.ace.tui.test_link_index_chips import (
    test_awaits_rows_index_with_perspective_labels_and_no_write,
    test_directed_relation_has_perspective_corrected_labels,
    test_duplicate_rows_across_projects_converge_to_max_uses,
    test_empty_snapshot_yields_empty_index,
    test_ordering_puts_semantic_relations_before_observational,
    test_projected_row_is_not_writable,
    test_symmetric_related_labels_both_directions_the_same,
    test_tolerant_count_coercion_matches_legacy_aggregate_reader,
    test_tolerant_string_fields_match_legacy_aggregate_reader,
)
from tests.ace.tui.test_link_index_targets import (
    test_a_canonical_ref_is_never_shadowed_by_another_edges_alias,
    test_accent_lookup_count_does_not_scale_with_row_count,
    test_agent_alias_spellings_resolve_to_the_same_chips,
    test_chop_neighbor_has_no_target_but_gets_the_virtual_chop_style,
    test_every_ref_kind_resolves_a_neighbor_target_in_both_positions,
    test_fixed_pane_kinds_paint_their_pane_accent_and_icon,
    test_lazy_chip_style_uses_worker_captured_provider_context,
    test_lazy_mappings_refuse_graph_enumeration,
    test_lazy_mappings_support_membership_without_enumeration,
    test_plan_ref_plan_alias_resolves_to_the_same_chips,
    test_stitch_short_sha_alias_resolves_to_the_same_chips,
)

__test__ = False

__all__ = [
    "test_a_canonical_ref_is_never_shadowed_by_another_edges_alias",
    "test_accent_lookup_count_does_not_scale_with_row_count",
    "test_agent_alias_spellings_resolve_to_the_same_chips",
    "test_awaits_rows_index_with_perspective_labels_and_no_write",
    "test_chop_neighbor_has_no_target_but_gets_the_virtual_chop_style",
    "test_clear_epoch_fences_pending_generation_but_releases_its_caller",
    "test_concurrent_requests_for_one_snapshot_compile_once",
    "test_directed_relation_has_perspective_corrected_labels",
    "test_distinct_synthetic_snapshots_with_shared_keys_stay_separate",
    "test_duplicate_rows_across_projects_converge_to_max_uses",
    "test_empty_snapshot_yields_empty_index",
    "test_every_ref_kind_resolves_a_neighbor_target_in_both_positions",
    "test_evicted_scope_keeps_pending_generation_fence",
    "test_failed_build_unblocks_waiters_and_retry_succeeds",
    "test_fixed_pane_kinds_paint_their_pane_accent_and_icon",
    "test_lazy_chip_style_uses_worker_captured_provider_context",
    "test_lazy_mappings_refuse_graph_enumeration",
    "test_lazy_mappings_support_membership_without_enumeration",
    "test_ordering_puts_semantic_relations_before_observational",
    "test_plan_ref_plan_alias_resolves_to_the_same_chips",
    "test_projected_row_is_not_writable",
    "test_requested_chip_cache_is_bounded_and_refills_after_eviction",
    "test_stitch_short_sha_alias_resolves_to_the_same_chips",
    "test_symmetric_related_labels_both_directions_the_same",
    "test_tolerant_count_coercion_matches_legacy_aggregate_reader",
    "test_tolerant_string_fields_match_legacy_aggregate_reader",
]
