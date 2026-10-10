"""Service-level tests for the unified named-proc supervisor.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_procs_service_settlement import (
    test_known_outcome_survives_reboot_fallback,
    test_nonzero_timeout_and_stop_survive_settlement_crash,
    test_settlement_recovers_every_injected_crash_checkpoint_repeatedly,
    test_settlement_resumes_after_an_injected_crash,
    test_stop_records_intent_then_settles_killed,
    test_supervisor_resume_keeps_frozen_success_after_settlement_crash,
    test_two_recovery_observers_publish_one_successful_result,
    test_unobserved_pre_reboot_command_stays_unknown,
    test_unobserved_same_boot_loss_does_not_claim_reboot,
    test_wait_for_proc_recovers_after_an_early_settlement_reconcile,
)
from tests.test_procs_service_submit import (
    test_ack_timeout_settles_as_launch_failure,
    test_barrier_timeout_does_not_run_the_command,
    test_legacy_rows_still_reconcile_without_settlement,
    test_named_named_proc_reuse_is_project_scoped_and_waits_for_settlement,
    test_result_and_artifact_settlement_are_durable,
    test_submit_derives_bare_named_named_proc,
    test_submit_records_a_named_proc_and_settles_success,
    test_submit_request_normalizes_legacy_kind_to_command,
    test_submit_request_replay_returns_the_active_row,
    test_total_and_idle_timeouts_settle_as_errors,
)

__test__ = False

__all__ = [
    "test_ack_timeout_settles_as_launch_failure",
    "test_barrier_timeout_does_not_run_the_command",
    "test_known_outcome_survives_reboot_fallback",
    "test_legacy_rows_still_reconcile_without_settlement",
    "test_named_named_proc_reuse_is_project_scoped_and_waits_for_settlement",
    "test_nonzero_timeout_and_stop_survive_settlement_crash",
    "test_result_and_artifact_settlement_are_durable",
    "test_settlement_recovers_every_injected_crash_checkpoint_repeatedly",
    "test_settlement_resumes_after_an_injected_crash",
    "test_stop_records_intent_then_settles_killed",
    "test_submit_derives_bare_named_named_proc",
    "test_submit_records_a_named_proc_and_settles_success",
    "test_submit_request_normalizes_legacy_kind_to_command",
    "test_submit_request_replay_returns_the_active_row",
    "test_supervisor_resume_keeps_frozen_success_after_settlement_crash",
    "test_total_and_idle_timeouts_settle_as_errors",
    "test_two_recovery_observers_publish_one_successful_result",
    "test_unobserved_pre_reboot_command_stays_unknown",
    "test_unobserved_same_boot_loss_does_not_claim_reboot",
    "test_wait_for_proc_recovers_after_an_early_settlement_reconcile",
]
