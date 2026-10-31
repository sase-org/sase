"""Host-owned workflow completion seam for staged HITL reviews.

The public test import path stays here; implementation tests live in focused,
private modules so pytest collects them only through this facade.
"""

from tests._workflow_completion_helpers import PROVIDER_RESPONSE, RUN_ID
from tests._workflow_completion_invoke import (
    test_deferred_evidence_registry_round_trip,
    test_deferred_invoke_skips_finalizers_and_records_evidence,
    test_invoke_provider_for_review_refuses_missing_evidence,
    test_invoke_provider_for_review_returns_completed_evidence,
    test_prepare_agent_review_requires_provider_evidence,
    test_prepare_review_rejects_unknown_step_type,
    test_prepare_script_review_needs_no_evidence,
)
from tests._workflow_completion_executor import (
    test_agent_review_uses_deferred_provider_and_preserves_real_response,
    test_embedded_review_suspension_runs_embedded_finally_steps,
    test_failed_cleanup_keeps_staged_review_unsettled,
    test_runner_returns_explicit_suspension_result,
    test_script_review_suspends_control_flow_and_runs_finally_before_settlement,
)
from tests._workflow_completion_settle import (
    test_complete_clean_prompt_with_no_submission,
    test_complete_prompt_review_with_accepted_submission,
    test_complete_script_review_after_finalized_prompt,
    test_complete_script_review_that_dirties_repo_carries,
    test_finalizer_failure_leaves_stage_held,
    test_host_admission_allows_review_despite_submission,
    test_host_second_handoff_is_refused,
    test_staged_workflow_review_freezes_path_output_before_finalizers,
)

__all__ = [
    "PROVIDER_RESPONSE",
    "RUN_ID",
    "test_agent_review_uses_deferred_provider_and_preserves_real_response",
    "test_complete_clean_prompt_with_no_submission",
    "test_complete_prompt_review_with_accepted_submission",
    "test_complete_script_review_after_finalized_prompt",
    "test_complete_script_review_that_dirties_repo_carries",
    "test_deferred_evidence_registry_round_trip",
    "test_deferred_invoke_skips_finalizers_and_records_evidence",
    "test_embedded_review_suspension_runs_embedded_finally_steps",
    "test_failed_cleanup_keeps_staged_review_unsettled",
    "test_finalizer_failure_leaves_stage_held",
    "test_host_admission_allows_review_despite_submission",
    "test_host_second_handoff_is_refused",
    "test_invoke_provider_for_review_refuses_missing_evidence",
    "test_invoke_provider_for_review_returns_completed_evidence",
    "test_prepare_agent_review_requires_provider_evidence",
    "test_prepare_review_rejects_unknown_step_type",
    "test_prepare_script_review_needs_no_evidence",
    "test_runner_returns_explicit_suspension_result",
    "test_script_review_suspends_control_flow_and_runs_finally_before_settlement",
    "test_staged_workflow_review_freezes_path_output_before_finalizers",
]
