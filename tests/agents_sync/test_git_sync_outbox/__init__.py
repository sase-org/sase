"""Git-sync outbox tests.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_git_sync_outbox`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_git_sync_outbox.test_bounded_retry import (
    test_bounded_retry_leaves_referenced_by_queue_untouched,
    test_bounded_retry_replays_failed_push_then_drains_two_batches_once,
)
from tests.agents_sync.test_git_sync_outbox.test_retry_retired import (
    test_retry_retired_acknowledges_a_session_page_not_an_unrelated_readme,
    test_retry_retired_does_not_ack_a_page_without_the_requested_revision,
    test_retry_retired_does_not_clear_referenced_by_terminal_rows,
    test_retry_retired_e2e_publishes_to_a_local_bare_remote,
    test_retry_retired_handles_multiple_primary_revisions,
    test_retry_retired_leaves_failed_push_retryable_and_isolates_projects,
    test_retry_retired_revives_and_acknowledges_a_legacy_mismatch,
)
from tests.agents_sync.test_git_sync_outbox.test_sync import (
    test_all_project_sync_isolates_failures,
    test_drop_retired_removes_only_retired_requests_and_reports_them,
    test_full_sync_acknowledges_publication_outbox_after_success,
    test_full_sync_keeps_outbox_request_when_agent_page_did_not_materialize,
    test_sync_without_drop_retired_keeps_and_reports_retired_requests,
)

__all__ = [
    "test_all_project_sync_isolates_failures",
    "test_bounded_retry_leaves_referenced_by_queue_untouched",
    "test_bounded_retry_replays_failed_push_then_drains_two_batches_once",
    "test_drop_retired_removes_only_retired_requests_and_reports_them",
    "test_full_sync_acknowledges_publication_outbox_after_success",
    "test_full_sync_keeps_outbox_request_when_agent_page_did_not_materialize",
    "test_retry_retired_acknowledges_a_session_page_not_an_unrelated_readme",
    "test_retry_retired_does_not_ack_a_page_without_the_requested_revision",
    "test_retry_retired_does_not_clear_referenced_by_terminal_rows",
    "test_retry_retired_e2e_publishes_to_a_local_bare_remote",
    "test_retry_retired_handles_multiple_primary_revisions",
    "test_retry_retired_leaves_failed_push_retryable_and_isolates_projects",
    "test_retry_retired_revives_and_acknowledges_a_legacy_mismatch",
    "test_sync_without_drop_retired_keeps_and_reports_retired_requests",
]
