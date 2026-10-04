"""Publication-outbox tests.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_publication_outbox`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_publication_outbox.test_queue import (
    test_diagnostics_separate_retryable_quarantine_from_retired_requests,
    test_outbox_is_idempotent_updates_digest_and_acknowledges,
    test_repeated_item_failure_is_quarantined_and_manually_clearable,
    test_repeated_terminal_failure_retires_without_quarantining,
    test_retry_quarantined_keeps_terminal_retired,
    test_two_workers_enqueue_without_lost_or_duplicate_requests,
)
from tests.agents_sync.test_publication_outbox.test_revive import (
    test_revive_can_select_retired_and_quarantined_together,
    test_revive_preserves_a_concurrent_enqueue,
    test_revive_retired_resets_selected_rows_and_preserves_identity,
)
from tests.agents_sync.test_publication_outbox.test_schema import (
    test_lock_free_snapshot_reads_schema_v1_without_writing,
    test_schema_v1_backlog_is_read_and_upgraded_without_data_loss,
    test_schema_v2_backlog_loads_without_terminal_state_and_upgrades,
    test_schema_v2_snapshot_requires_quarantine_state,
    test_schema_v3_agent_request_loads_with_same_logical_key,
    test_schema_v4_drops_non_agent_requests_with_a_visible_diagnostic,
    test_typed_snapshot_rejects_malformed_consumed_fields,
)

__all__ = [
    "test_diagnostics_separate_retryable_quarantine_from_retired_requests",
    "test_lock_free_snapshot_reads_schema_v1_without_writing",
    "test_outbox_is_idempotent_updates_digest_and_acknowledges",
    "test_repeated_item_failure_is_quarantined_and_manually_clearable",
    "test_repeated_terminal_failure_retires_without_quarantining",
    "test_retry_quarantined_keeps_terminal_retired",
    "test_revive_can_select_retired_and_quarantined_together",
    "test_revive_preserves_a_concurrent_enqueue",
    "test_revive_retired_resets_selected_rows_and_preserves_identity",
    "test_schema_v1_backlog_is_read_and_upgraded_without_data_loss",
    "test_schema_v2_backlog_loads_without_terminal_state_and_upgrades",
    "test_schema_v2_snapshot_requires_quarantine_state",
    "test_schema_v3_agent_request_loads_with_same_logical_key",
    "test_schema_v4_drops_non_agent_requests_with_a_visible_diagnostic",
    "test_two_workers_enqueue_without_lost_or_duplicate_requests",
    "test_typed_snapshot_rejects_malformed_consumed_fields",
]
