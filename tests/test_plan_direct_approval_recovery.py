"""Coder recovery for gateless ``sase plan approve`` runs.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_plan_direct_approval_recovery_diagnosis import (
    test_handled_age_uses_handled_at,
    test_inspect_hint_prefers_committed_ref,
    test_receipt_round_trips_recovery_fields,
    test_recovery_receipt_wording,
    test_refusal_hint_prints_once,
    test_response_refines_approve_commit_to_tale,
)
from tests.test_plan_direct_approval_recovery_evaluate import (
    test_committed_done_with_unknown_coder_refuses,
    test_commit_receipt_with_launch_error_recovers,
    test_crash_receipt_recovers_again,
    test_direct_non_coder_receipt_keeps_refusal,
    test_fresh_histories_keep_refusal,
    test_gate_coder_used_when_receipt_lost_race,
    test_handled_tale_failed_coder_recovers,
    test_live_coder_refuses,
    test_missing_gate_turn_and_no_code_recovers,
    test_non_coder_histories_keep_refusal,
    test_second_run_with_live_replacement_refuses,
    test_succeeded_coder_refuses,
)
from tests.test_plan_direct_approval_recovery_execute import (
    test_executor_agent_guard,
    test_executor_launch_failure_records_error,
    test_executor_launches_one_coder_and_writes_receipt,
    test_executor_lock_recheck_refuses_without_launching,
)
from tests.test_plan_direct_approval_recovery_followup import (
    test_gate_followup_falls_back_to_registered_code,
    test_gate_followup_prefers_verified_shell,
    test_prior_coder_words,
)
from tests.test_plan_direct_approval_recovery_resolve import (
    test_resolver_explicit_commit_keeps_handled_refusal,
    test_resolver_live_verdict_refuses_coder_running,
    test_resolver_returns_recovery_plan,
)

__test__ = False

__all__ = [
    "test_committed_done_with_unknown_coder_refuses",
    "test_commit_receipt_with_launch_error_recovers",
    "test_crash_receipt_recovers_again",
    "test_direct_non_coder_receipt_keeps_refusal",
    "test_executor_agent_guard",
    "test_executor_launch_failure_records_error",
    "test_executor_launches_one_coder_and_writes_receipt",
    "test_executor_lock_recheck_refuses_without_launching",
    "test_fresh_histories_keep_refusal",
    "test_gate_coder_used_when_receipt_lost_race",
    "test_gate_followup_falls_back_to_registered_code",
    "test_gate_followup_prefers_verified_shell",
    "test_handled_age_uses_handled_at",
    "test_handled_tale_failed_coder_recovers",
    "test_inspect_hint_prefers_committed_ref",
    "test_live_coder_refuses",
    "test_missing_gate_turn_and_no_code_recovers",
    "test_non_coder_histories_keep_refusal",
    "test_prior_coder_words",
    "test_receipt_round_trips_recovery_fields",
    "test_recovery_receipt_wording",
    "test_refusal_hint_prints_once",
    "test_resolver_explicit_commit_keeps_handled_refusal",
    "test_resolver_live_verdict_refuses_coder_running",
    "test_resolver_returns_recovery_plan",
    "test_response_refines_approve_commit_to_tale",
    "test_second_run_with_live_replacement_refuses",
    "test_succeeded_coder_refuses",
]
