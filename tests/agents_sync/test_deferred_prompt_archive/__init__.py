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
    test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt,
    test_full_sync_keeps_the_request_when_the_original_prompt_source_is_gone,
    test_full_sync_parks_a_blocked_prompt_without_charging_attempts,
    test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred,
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
    "test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt",
    "test_full_sync_keeps_the_request_when_the_original_prompt_source_is_gone",
    "test_full_sync_parks_a_blocked_prompt_without_charging_attempts",
    "test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred",
]
