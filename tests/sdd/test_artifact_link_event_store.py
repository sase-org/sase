"""Public import facade for artifact-link event-store tests.

The test cases live in focused modules; these re-exports preserve the original
module path for callers that import the test functions directly.
"""

from tests.sdd._artifact_link_event_store_test_helpers import PROJECT_KEY
from tests.sdd.test_artifact_link_event_store_core import (
    test_duplicate_endpoint_event_objects_reduce_once,
    test_event_ordering_chooses_newest_edge_put,
    test_imported_cutover_ignores_legacy_rows_when_events_overlap,
    test_legacy_event_overlap_rejected_before_cutover,
    test_pending_event_outbox_entries_are_visible_with_age_stats,
    test_pending_read_events_increment_legacy_rows_without_overlap_rejection,
    test_projected_rows_do_not_become_durable_store_truth,
    test_reconciliation_reduces_event_union_before_deduping_rows,
    test_reconciliation_unions_tombstones_with_sibling_observations,
    test_alias_event_reduces_late_old_ref_observation_to_new_ref,
)
from tests.sdd.test_artifact_link_event_store_health import (
    test_event_health_reports_orphaned_tombstones,
    test_orphaned_pending_tombstone_does_not_block_unrelated_reads,
    test_orphaned_tombstone_converges_when_predecessor_arrives,
    test_orphaned_tombstone_does_not_block_unrelated_durable_reads,
    test_orphaned_tombstone_prevents_legacy_fallback_resurrection,
)
from tests.sdd.test_artifact_link_event_store_snapshot import (
    test_covers_row_caches_alias_resolution_failure,
    test_covers_row_caches_edge_identities,
    test_covers_row_resolves_aliases_with_one_binding_call,
)

__test__ = False

__all__ = [
    "PROJECT_KEY",
    "test_duplicate_endpoint_event_objects_reduce_once",
    "test_event_ordering_chooses_newest_edge_put",
    "test_imported_cutover_ignores_legacy_rows_when_events_overlap",
    "test_legacy_event_overlap_rejected_before_cutover",
    "test_pending_event_outbox_entries_are_visible_with_age_stats",
    "test_pending_read_events_increment_legacy_rows_without_overlap_rejection",
    "test_projected_rows_do_not_become_durable_store_truth",
    "test_reconciliation_reduces_event_union_before_deduping_rows",
    "test_reconciliation_unions_tombstones_with_sibling_observations",
    "test_alias_event_reduces_late_old_ref_observation_to_new_ref",
    "test_event_health_reports_orphaned_tombstones",
    "test_orphaned_pending_tombstone_does_not_block_unrelated_reads",
    "test_orphaned_tombstone_converges_when_predecessor_arrives",
    "test_orphaned_tombstone_does_not_block_unrelated_durable_reads",
    "test_orphaned_tombstone_prevents_legacy_fallback_resurrection",
    "test_covers_row_caches_alias_resolution_failure",
    "test_covers_row_caches_edge_identities",
    "test_covers_row_resolves_aliases_with_one_binding_call",
]
