"""Bounded report-and-apply repair for already-published run states.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_publication_state_repair`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_publication_state_repair._helpers import (
    FINISHED,
    OWNER,
    PROJECT,
    STARTED,
)
from tests.agents_sync.test_publication_state_repair.test_basic_repair import (
    test_completed_repair_converges_remote_snapshot_manifest_and_pages,
    test_dismissed_evidence_repairs_to_dismissed,
    test_failed_evidence_repairs_to_failed,
    test_live_runs_stay_live_with_no_write_cursor_advance,
    test_no_new_hood_enrollment,
    test_preview_is_read_only_and_scoped,
    test_unresolvable_rows_leave_state_unchanged,
)
from tests.agents_sync.test_publication_state_repair.test_bounds import (
    test_byte_budget_freezes_cursor,
    test_collect_reads_owner_manifest_constant_times,
    test_corrupt_hood_does_not_block_sibling,
    test_cursor_pagination_and_invalid_cursor,
    test_second_pass_is_noop,
    test_window_hood_cap,
    test_withheld_run_does_not_block_sibling,
)
from tests.agents_sync.test_publication_state_repair.test_preservation_retry import (
    test_foreign_owner_preservation,
    test_lock_busy_is_benign_skip,
    test_non_fast_forward_push_recomputes_and_retries,
    test_published_terminal_preserved_against_stale_active,
    test_push_failure_then_retry_converges,
    test_reused_name_different_identity_never_borrows,
)

__all__ = [
    "FINISHED",
    "OWNER",
    "PROJECT",
    "STARTED",
    "test_byte_budget_freezes_cursor",
    "test_collect_reads_owner_manifest_constant_times",
    "test_completed_repair_converges_remote_snapshot_manifest_and_pages",
    "test_corrupt_hood_does_not_block_sibling",
    "test_cursor_pagination_and_invalid_cursor",
    "test_dismissed_evidence_repairs_to_dismissed",
    "test_failed_evidence_repairs_to_failed",
    "test_foreign_owner_preservation",
    "test_live_runs_stay_live_with_no_write_cursor_advance",
    "test_lock_busy_is_benign_skip",
    "test_no_new_hood_enrollment",
    "test_non_fast_forward_push_recomputes_and_retries",
    "test_preview_is_read_only_and_scoped",
    "test_published_terminal_preserved_against_stale_active",
    "test_push_failure_then_retry_converges",
    "test_reused_name_different_identity_never_borrows",
    "test_second_pass_is_noop",
    "test_unresolvable_rows_leave_state_unchanged",
    "test_window_hood_cap",
    "test_withheld_run_does_not_block_sibling",
]
