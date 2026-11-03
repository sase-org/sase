"""Public import facade for prepared-bridge finalizer tests.

Pytest collects the focused modules directly; this facade preserves the original
module path for callers that import the public test functions.
"""

__test__ = False

from .test_finalizers_prepared_bridge_coverage import (
    test_reservation_from_staged_payload_parses_and_rejects_malformed,
    test_host_completion_receipt_blocks_starter_omit,
    test_reserved_starter_omits_submission_after_handoff_only_change,
    test_already_bound_starter_omits_submission_without_reservation,
    test_prepared_without_reservation_does_not_fall_back_to_carry,
    test_malformed_reservation_refuses_coverage,
    test_observation_drift_refuses_coverage,
    test_owner_drift_refuses_coverage,
    test_command_drift_refuses_coverage,
    test_plan_digest_drift_refuses_adapter_coverage,
    test_non_root_rename_does_not_reuse_prepared_creator_identity,
    test_different_run_does_not_reuse_prepared_creator_identity,
    test_uncovered_new_work_still_requires_submission,
)
from .test_finalizers_prepared_bridge_lifecycle import (
    test_promoted_prepared_starter_and_nonce_free_host_completion_commit_on_green,
    test_ineligible_red_execution_does_not_commit,
    test_host_completion_installs_sealed_declaration_after_starter_satisfaction,
)

__all__ = [
    "test_reservation_from_staged_payload_parses_and_rejects_malformed",
    "test_host_completion_receipt_blocks_starter_omit",
    "test_reserved_starter_omits_submission_after_handoff_only_change",
    "test_already_bound_starter_omits_submission_without_reservation",
    "test_prepared_without_reservation_does_not_fall_back_to_carry",
    "test_malformed_reservation_refuses_coverage",
    "test_observation_drift_refuses_coverage",
    "test_owner_drift_refuses_coverage",
    "test_command_drift_refuses_coverage",
    "test_plan_digest_drift_refuses_adapter_coverage",
    "test_non_root_rename_does_not_reuse_prepared_creator_identity",
    "test_different_run_does_not_reuse_prepared_creator_identity",
    "test_uncovered_new_work_still_requires_submission",
    "test_promoted_prepared_starter_and_nonce_free_host_completion_commit_on_green",
    "test_ineligible_red_execution_does_not_commit",
    "test_host_completion_installs_sealed_declaration_after_starter_satisfaction",
]
