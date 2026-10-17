"""Parity tests for the Rust bead mutation facade.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_core_facade.test_bead_mutation_claim import (
    test_claim_for_agent_launch_attaches_only_when_close_predates_submission,
    test_claim_for_agent_launch_converts_issue_and_reassigns,
    test_claim_for_agent_launch_maps_missing_and_preserves_specific_failures,
    test_fractional_and_equal_submission_timestamps_attach,
    test_future_allocated_launch_id_does_not_make_queued_close_attach,
    test_preclaim_epic_work_allows_empty_subset_without_land_mutation,
    test_preclaim_epic_work_converts_batch_and_returns_prior_state,
    test_ready_to_work_errors_map_to_python_exceptions,
    test_wait_claim_facade_claims_idempotently_and_releases,
)
from tests.test_core_facade.test_bead_mutation_operations import (
    test_append_note_facade_returns_issue_and_export_reflects_note,
    test_external_ref_facade_create_update_clear_and_conflict,
    test_mutation_facade_jsonl_matches_python_after_each_operation,
    test_mutation_facade_refuses_unsandboxed_pytest_store_before_binding,
    test_mutation_facade_writes_events_and_repairs_jsonl_projection,
    test_remove_many_facade_returns_unique_expanded_removals,
    test_set_link_projections_batch_is_authorized_and_returns_aggregate,
    test_set_link_projections_refuses_unsandboxed_pytest_store_before_binding,
)

__test__ = False

__all__ = [
    "test_append_note_facade_returns_issue_and_export_reflects_note",
    "test_claim_for_agent_launch_attaches_only_when_close_predates_submission",
    "test_claim_for_agent_launch_converts_issue_and_reassigns",
    "test_claim_for_agent_launch_maps_missing_and_preserves_specific_failures",
    "test_external_ref_facade_create_update_clear_and_conflict",
    "test_fractional_and_equal_submission_timestamps_attach",
    "test_future_allocated_launch_id_does_not_make_queued_close_attach",
    "test_mutation_facade_jsonl_matches_python_after_each_operation",
    "test_mutation_facade_refuses_unsandboxed_pytest_store_before_binding",
    "test_mutation_facade_writes_events_and_repairs_jsonl_projection",
    "test_preclaim_epic_work_allows_empty_subset_without_land_mutation",
    "test_preclaim_epic_work_converts_batch_and_returns_prior_state",
    "test_ready_to_work_errors_map_to_python_exceptions",
    "test_remove_many_facade_returns_unique_expanded_removals",
    "test_set_link_projections_batch_is_authorized_and_returns_aggregate",
    "test_set_link_projections_refuses_unsandboxed_pytest_store_before_binding",
    "test_wait_claim_facade_claims_idempotently_and_releases",
]
