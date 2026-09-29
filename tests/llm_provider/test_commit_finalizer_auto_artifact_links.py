"""Finalizer reconciliation for implicit artifact-link index writes.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.llm_provider.test_commit_finalizer_auto_artifact_links_executor import (
    test_executor_commits_declared_legacy_link_index_through_stitch,
    test_executor_commits_mixed_report_and_legacy_link_index_together,
    test_executor_rejects_artifact_link_auto_commit_without_new_marker,
)
from tests.llm_provider.test_commit_finalizer_auto_artifact_links_reconciliation import (
    test_malformed_candidates_remain_dirty,
    test_mixed_unrelated_dirt_is_left_for_the_declaration,
    test_multiple_sidecars_commit_once_each,
    test_pre_existing_dirty_index_is_not_auto_committed,
    test_publication_failure_is_recoverable,
    test_two_implicit_plan_reads_produce_no_dirt_or_commit,
)

__test__ = False

__all__ = [
    "test_executor_commits_declared_legacy_link_index_through_stitch",
    "test_executor_commits_mixed_report_and_legacy_link_index_together",
    "test_executor_rejects_artifact_link_auto_commit_without_new_marker",
    "test_malformed_candidates_remain_dirty",
    "test_mixed_unrelated_dirt_is_left_for_the_declaration",
    "test_multiple_sidecars_commit_once_each",
    "test_pre_existing_dirty_index_is_not_auto_committed",
    "test_publication_failure_is_recoverable",
    "test_two_implicit_plan_reads_produce_no_dirt_or_commit",
]
