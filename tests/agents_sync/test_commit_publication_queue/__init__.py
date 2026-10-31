"""Commit-publication queue tests.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_commit_publication_queue`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_commit_publication_queue.test_drain import (
    test_bounded_drain_publishes_only_the_supplied_logical_keys,
    test_failed_targeted_publish_cleans_uncommitted_payload,
    test_large_backlog_builds_one_inventory_and_publishes_each_hood_once,
)
from tests.agents_sync.test_commit_publication_queue.test_enqueue import (
    test_committed_publication_records_a_retryable_request_when_git_fails,
    test_linked_repo_commit_enqueues_linked_scope,
)
from tests.agents_sync.test_commit_publication_queue.test_failures import (
    test_mixed_queue_publishes_good_items_and_quarantines_only_bad_item,
    test_no_publishable_runs_retries_once_then_retires,
    test_repeated_format_publication_failure_retires_and_doctor_says_drop,
)

__all__ = [
    "test_bounded_drain_publishes_only_the_supplied_logical_keys",
    "test_committed_publication_records_a_retryable_request_when_git_fails",
    "test_failed_targeted_publish_cleans_uncommitted_payload",
    "test_large_backlog_builds_one_inventory_and_publishes_each_hood_once",
    "test_linked_repo_commit_enqueues_linked_scope",
    "test_mixed_queue_publishes_good_items_and_quarantines_only_bad_item",
    "test_no_publishable_runs_retries_once_then_retires",
    "test_repeated_format_publication_failure_retires_and_doctor_says_drop",
]
