"""Tests for dismissed bundle indexing.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_dismissed_bundle_index_rebuild import (
    test_dismissed_bundle_index_rebuild_and_query,
    test_dismissed_bundle_index_schema_mismatch_recreates_table,
    test_ensure_dismissed_archive_ready_builds_index,
    test_rebuild_indexes_newest_shards_first_and_reports_progress,
    test_rebuild_quarantines_and_recreates_corrupt_index,
    test_v2_index_is_refilled_by_archive_ready_check,
)
from tests.test_dismissed_bundle_index_summaries import (
    test_dismissed_bundle_index_query_summaries_supports_offset,
    test_dismissed_bundle_index_summary_fields,
    test_load_dismissed_bundles_by_suffix_uses_legacy_index,
    test_summary_does_not_treat_stop_time_as_dismissed_at,
)
from tests.test_dismissed_bundle_index_verify import (
    test_dismissed_bundle_identities_snapshot_reuses_unchanged_signature,
    test_dismissed_bundle_identity_query_missing_and_schema_less_are_read_only,
    test_dismissed_bundle_identity_snapshot_real_index_is_read_only,
    test_dismissed_bundle_verify_detects_changed_file_signature,
    test_dismissed_bundle_verify_reports_stale_and_missing_rows,
    test_dismissed_bundle_verify_skips_json_parse_of_indexed_bundles,
    test_dismissed_bundle_verify_treats_unindexed_corrupt_file_as_corrupt,
    test_load_dismissed_bundle_identities_matches_summary_projection,
)

__test__ = False

__all__ = [
    "test_dismissed_bundle_identities_snapshot_reuses_unchanged_signature",
    "test_dismissed_bundle_identity_query_missing_and_schema_less_are_read_only",
    "test_dismissed_bundle_identity_snapshot_real_index_is_read_only",
    "test_dismissed_bundle_index_query_summaries_supports_offset",
    "test_dismissed_bundle_index_rebuild_and_query",
    "test_dismissed_bundle_index_schema_mismatch_recreates_table",
    "test_dismissed_bundle_index_summary_fields",
    "test_dismissed_bundle_verify_detects_changed_file_signature",
    "test_dismissed_bundle_verify_reports_stale_and_missing_rows",
    "test_dismissed_bundle_verify_skips_json_parse_of_indexed_bundles",
    "test_dismissed_bundle_verify_treats_unindexed_corrupt_file_as_corrupt",
    "test_ensure_dismissed_archive_ready_builds_index",
    "test_load_dismissed_bundle_identities_matches_summary_projection",
    "test_load_dismissed_bundles_by_suffix_uses_legacy_index",
    "test_rebuild_indexes_newest_shards_first_and_reports_progress",
    "test_rebuild_quarantines_and_recreates_corrupt_index",
    "test_summary_does_not_treat_stop_time_as_dismissed_at",
    "test_v2_index_is_refilled_by_archive_ready_check",
]
