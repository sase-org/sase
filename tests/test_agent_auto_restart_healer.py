"""Tests for the update-skew healer phase (ledger claim, skips, relaunch).

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_agent_auto_restart_healer_claim import (
    test_dead_launching_claim_settles_without_relaunching,
    test_decline_matrix_silenced_vs_quiet,
    test_deferral_expires_from_first_claim_across_retakes,
    test_expired_deferred_claim_escalates_loudly,
    test_live_launching_claim_defers,
    test_replacement_failure_escalates_once_and_marks_recovery,
    test_stale_claim_takeover_rewrites_claimer,
)
from tests.test_agent_auto_restart_healer_flow import (
    test_healer_defers_when_probe_fails,
    test_healer_relaunches_once_then_declines,
    test_quiescence_failure_does_not_run_probe,
    test_real_classifier_reclassifies_incident_after_probe,
)
from tests.test_agent_auto_restart_healer_guards import (
    test_attach_provenance_fills_from_identity_and_file_proof,
    test_claimer_liveness_dead_pid_and_self,
    test_gate_off_when_config_disabled,
    test_gate_on_when_config_enabled,
    test_no_skip_for_plain_failed_row,
    test_pending_targets_are_topological_then_least_progress_first,
    test_probe_imports_stdlib_cleanly,
    test_probe_reports_missing_module,
    test_quiescence_returns_a_reason,
    test_skip_already_restarted,
    test_skip_killed_outcome,
    test_skip_non_failed_row,
    test_skip_remote_row,
    test_storm_breaker_trips_and_resume_rearms,
    test_storm_window_counts_only_launches,
)

__test__ = False

__all__ = [
    "test_attach_provenance_fills_from_identity_and_file_proof",
    "test_claimer_liveness_dead_pid_and_self",
    "test_dead_launching_claim_settles_without_relaunching",
    "test_decline_matrix_silenced_vs_quiet",
    "test_deferral_expires_from_first_claim_across_retakes",
    "test_expired_deferred_claim_escalates_loudly",
    "test_gate_off_when_config_disabled",
    "test_gate_on_when_config_enabled",
    "test_healer_defers_when_probe_fails",
    "test_healer_relaunches_once_then_declines",
    "test_live_launching_claim_defers",
    "test_no_skip_for_plain_failed_row",
    "test_pending_targets_are_topological_then_least_progress_first",
    "test_probe_imports_stdlib_cleanly",
    "test_probe_reports_missing_module",
    "test_quiescence_failure_does_not_run_probe",
    "test_quiescence_returns_a_reason",
    "test_real_classifier_reclassifies_incident_after_probe",
    "test_replacement_failure_escalates_once_and_marks_recovery",
    "test_skip_already_restarted",
    "test_skip_killed_outcome",
    "test_skip_non_failed_row",
    "test_skip_remote_row",
    "test_stale_claim_takeover_rewrites_claimer",
    "test_storm_breaker_trips_and_resume_rearms",
    "test_storm_window_counts_only_launches",
]
