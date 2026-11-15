"""Deferred prompt-archive tests.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_deferred_prompt_archive`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_deferred_prompt_archive.test_acknowledgment import (
    test_acknowledged_deferred_archives_record_side_effects_once_per_request,
    test_deferred_acknowledgment_charges_its_own_cites_persist_failure,
    test_deferred_acknowledgment_ignores_unrelated_referenced_by_drain_failure,
    test_deferred_archive_matches_sync_after_workspace_head_moves,
)
from tests.agents_sync.test_deferred_prompt_archive.test_full_sync import (
    test_full_sync_escalates_unresolved_prompt_after_grace_window,
    test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt,
    test_full_sync_keeps_the_request_when_the_original_prompt_source_is_gone,
    test_full_sync_parks_a_blocked_prompt_without_charging_attempts,
    test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred,
)
from tests.agents_sync.test_deferred_prompt_archive.test_grace import (
    test_pending_predicate_legacy_created_at_is_past_grace,
    test_pending_predicate_past_grace,
    test_pending_predicate_rejects_non_unavailable_status,
    test_pending_predicate_rejects_other_reasons,
    test_pending_predicate_restore_error_is_never_pending,
    test_pending_predicate_young_unavailable,
    test_restore_error_is_not_pending_even_when_young,
    test_restore_escalates_legacy_created_at,
    test_restore_escalates_old_unavailable_request,
    test_restore_marks_young_unavailable_request_pending,
)
from tests.agents_sync.test_deferred_prompt_archive.test_land import (
    test_deferred_land_row_accepts_planner_archive_for_same_session_member,
    test_deferred_land_row_does_not_match_prefix_sharing_session,
)

__all__ = [
    "test_acknowledged_deferred_archives_record_side_effects_once_per_request",
    "test_deferred_acknowledgment_charges_its_own_cites_persist_failure",
    "test_deferred_acknowledgment_ignores_unrelated_referenced_by_drain_failure",
    "test_deferred_archive_matches_sync_after_workspace_head_moves",
    "test_deferred_land_row_accepts_planner_archive_for_same_session_member",
    "test_deferred_land_row_does_not_match_prefix_sharing_session",
    "test_full_sync_escalates_unresolved_prompt_after_grace_window",
    "test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt",
    "test_full_sync_keeps_the_request_when_the_original_prompt_source_is_gone",
    "test_full_sync_parks_a_blocked_prompt_without_charging_attempts",
    "test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred",
    "test_pending_predicate_legacy_created_at_is_past_grace",
    "test_pending_predicate_past_grace",
    "test_pending_predicate_rejects_non_unavailable_status",
    "test_pending_predicate_rejects_other_reasons",
    "test_pending_predicate_restore_error_is_never_pending",
    "test_pending_predicate_young_unavailable",
    "test_restore_error_is_not_pending_even_when_young",
    "test_restore_escalates_legacy_created_at",
    "test_restore_escalates_old_unavailable_request",
    "test_restore_marks_young_unavailable_request_pending",
]
