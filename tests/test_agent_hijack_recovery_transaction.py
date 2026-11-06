"""Compatibility facade for hijack recovery transaction tests.

The concrete tests live in focused modules. Keep their original import path available
without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from tests.test_agent_hijack_recovery_transaction_launch import (
    test_continue_full_transaction_launches_with_real_policy_and_persistence,
    test_escalate_full_transaction_pins_changed_model,
    test_instruct_edited_prompt_with_explicit_model_launches,
)
from tests.test_agent_hijack_recovery_transaction_resilience import (
    test_cancel_of_uncertain_dispatch_retains_resolving,
    test_concurrent_resolvers_create_one_request_and_child,
    test_crash_after_cas_resumes_the_same_attempt_without_a_child,
    test_disabled_provider_refuses_before_dispatch,
    test_failed_inheritance_never_runs_the_provider,
    test_failed_termination_retains_resolving_for_reconciliation,
    test_interrupted_settlement_replays_idempotently,
    test_uncertain_spawn_keeps_resolving_and_resumes_the_same_request,
)

__all__ = (
    "test_cancel_of_uncertain_dispatch_retains_resolving",
    "test_concurrent_resolvers_create_one_request_and_child",
    "test_continue_full_transaction_launches_with_real_policy_and_persistence",
    "test_crash_after_cas_resumes_the_same_attempt_without_a_child",
    "test_disabled_provider_refuses_before_dispatch",
    "test_escalate_full_transaction_pins_changed_model",
    "test_failed_inheritance_never_runs_the_provider",
    "test_failed_termination_retains_resolving_for_reconciliation",
    "test_instruct_edited_prompt_with_explicit_model_launches",
    "test_interrupted_settlement_replays_idempotently",
    "test_uncertain_spawn_keeps_resolving_and_resumes_the_same_request",
)

__test__ = False
