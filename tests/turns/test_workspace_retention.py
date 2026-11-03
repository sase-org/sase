"""Adapter tests for terminal workspace-retention settlement.

Split into focused modules; this module re-exports every public name so the
original import path keeps working. It collects no tests itself. Only public
names are re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

from tests.turns.test_workspace_retention_policy import (
    test_creator_restored_releases_even_when_dirty,
    test_different_workspace_successor_retains_original,
    test_gate_released_workspace_does_not_reacquire,
    test_historical_carried_to_does_not_count_as_successor,
    test_late_retention_publishes_recovery_notification,
    test_missing_baseline_with_custody_retains,
    test_primary_clean_linked_dirty_retains,
    test_probe_failure_retains_and_is_not_clean,
    test_proven_clean_releases_claim,
    test_repeated_hold_is_idempotent,
    test_same_workspace_successor_releases_without_hold,
    test_session_owned_dirt_pins_and_persists_record,
    test_staged_and_untracked_edits_retain,
    test_unchanged_foreign_dirt_releases,
)
from tests.turns.test_workspace_retention_records import (
    test_claim_transfer_racing_settlement_is_noop,
    test_explicit_dismissal_preserves_reused_claim_and_unresolved_record,
    test_explicit_dismissal_releases_exact_retained_claim_and_settles_record,
    test_historical_settled_boolean_without_timestamp_stays_unresolved,
    test_incomplete_owner_identity_does_not_mutate,
    test_metadata_write_failure_still_protects_custody,
    test_pending_retention_round_trip_and_owner_match,
    test_same_workspace_successor_settles_prior_retain_record,
    test_settled_record_survives_fresh_unresolved_hold,
    test_stale_ownership_probe_leaves_unresolved_retain,
    test_successful_release_clears_matching_occupant,
)

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

__all__ = [
    "test_claim_transfer_racing_settlement_is_noop",
    "test_creator_restored_releases_even_when_dirty",
    "test_different_workspace_successor_retains_original",
    "test_explicit_dismissal_preserves_reused_claim_and_unresolved_record",
    "test_explicit_dismissal_releases_exact_retained_claim_and_settles_record",
    "test_gate_released_workspace_does_not_reacquire",
    "test_historical_carried_to_does_not_count_as_successor",
    "test_historical_settled_boolean_without_timestamp_stays_unresolved",
    "test_incomplete_owner_identity_does_not_mutate",
    "test_late_retention_publishes_recovery_notification",
    "test_metadata_write_failure_still_protects_custody",
    "test_missing_baseline_with_custody_retains",
    "test_pending_retention_round_trip_and_owner_match",
    "test_primary_clean_linked_dirty_retains",
    "test_probe_failure_retains_and_is_not_clean",
    "test_proven_clean_releases_claim",
    "test_repeated_hold_is_idempotent",
    "test_same_workspace_successor_releases_without_hold",
    "test_same_workspace_successor_settles_prior_retain_record",
    "test_session_owned_dirt_pins_and_persists_record",
    "test_settled_record_survives_fresh_unresolved_hold",
    "test_stale_ownership_probe_leaves_unresolved_retain",
    "test_staged_and_untracked_edits_retain",
    "test_successful_release_clears_matching_occupant",
    "test_unchanged_foreign_dirt_releases",
]
