"""E4 verdict-completion: explicit no-new prepared completion on receipts."""

from __future__ import annotations

from ._no_new_receipt import needs_no_new_core
from .test_no_new_receipt_host import (
    test_freeze_failed_no_new_enters_host_completion,
    test_freeze_failed_pass_stays_on_recovery,
    test_host_completion_no_new_persists_verdict_provenance,
    test_host_completion_no_new_refusal_recovers_with_typed_reason,
    test_host_completion_no_new_shortcut_still_runs_precommit_gate,
    test_host_completion_pass_intent_never_calls_receipt_gate,
    test_host_completion_resume_reruns_gate_instead_of_trusting_success,
)
from .test_no_new_receipt_prepare import (
    test_ordinary_submit_records_unverified_provenance,
    test_prepare_defaults_to_pass_and_rejects_malformed_accept,
    test_prepare_seals_explicit_no_new,
)
from .test_no_new_receipt_verify import (
    test_intent_accept_defaults_to_pass,
    test_verify_accepts_pass_verdict_under_no_new_lookup,
    test_verify_happy_path_returns_auditable_evidence,
    test_verify_refuses_multi_repo_all_or_nothing,
    test_verify_rejects_command_verdict_and_policy_mismatch,
    test_verify_rejects_non_verify_and_unrelated_outcomes,
    test_verify_rejects_unsettled_lost_and_unowned_runs,
    test_verify_rejects_wrong_source_run_and_changed_receipt,
    test_verify_retains_typed_receipt_refusals,
)

pytest_plugins = ("tests.monitor._no_new_receipt",)

__all__ = [
    "needs_no_new_core",
    "test_freeze_failed_no_new_enters_host_completion",
    "test_freeze_failed_pass_stays_on_recovery",
    "test_host_completion_no_new_persists_verdict_provenance",
    "test_host_completion_no_new_refusal_recovers_with_typed_reason",
    "test_host_completion_no_new_shortcut_still_runs_precommit_gate",
    "test_host_completion_pass_intent_never_calls_receipt_gate",
    "test_host_completion_resume_reruns_gate_instead_of_trusting_success",
    "test_intent_accept_defaults_to_pass",
    "test_ordinary_submit_records_unverified_provenance",
    "test_prepare_defaults_to_pass_and_rejects_malformed_accept",
    "test_prepare_seals_explicit_no_new",
    "test_verify_accepts_pass_verdict_under_no_new_lookup",
    "test_verify_happy_path_returns_auditable_evidence",
    "test_verify_refuses_multi_repo_all_or_nothing",
    "test_verify_rejects_command_verdict_and_policy_mismatch",
    "test_verify_rejects_non_verify_and_unrelated_outcomes",
    "test_verify_rejects_unsettled_lost_and_unowned_runs",
    "test_verify_rejects_wrong_source_run_and_changed_receipt",
    "test_verify_retains_typed_receipt_refusals",
]
