"""Tests for run-agent-runner completion-notification behavior and metadata.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_run_agent_runner_notifications_flags import (
    test_completion_notification_omits_empty_output_variables,
    test_completion_notification_reads_commit_result_without_step_output,
    test_completion_notification_surfaces_terminal_retention_record,
    test_completion_notification_uses_full_commit_result_message,
    test_epic_approved_classifies_as_runner_success,
    test_epic_approved_without_publication_error_has_no_degraded_note,
    test_failed_notification_includes_held_workspace_recovery,
    test_failure_completion_notification_is_not_tagged_done,
    test_failure_error_report_notification_includes_output_variables,
    test_failure_error_report_notification_includes_runtime,
    test_gated_suppresses_completion_notification,
    test_hidden_agent_failure_still_silent,
    test_hidden_agent_forwards_silent_true,
    test_monitored_suppresses_completion_notification,
    test_plan_rejected_classifies_as_runner_success,
    test_plan_rejected_suppresses_completion_notification,
    test_real_failure_stays_runner_failure,
    test_sdd_publication_error_rides_deferred_epic_completion,
    test_success_completion_notification_includes_output_variables,
    test_success_completion_notification_includes_runtime,
    test_success_completion_notification_tags_done,
    test_visible_agent_forwards_silent_false,
)
from tests.test_run_agent_runner_notifications_handoff import (
    test_adopted_receipt_produces_no_held_note,
    test_failed_notification_names_held_staged_handoff,
    test_held_staged_handoff_note_names_exact_readopt_command,
    test_held_staged_handoff_without_recovery_evidence_prompts_salvage,
    test_malformed_receipt_produces_malformed_held_note,
    test_no_staged_files_produces_no_held_note,
)
from tests.test_run_agent_runner_notifications_identity import (
    test_completion_notification_adds_bead_display_for_bead_agent,
    test_completion_notification_bead_display_uses_agent_session_name,
    test_completion_notification_does_not_truncate_dotted_standalone_name,
    test_completion_notification_keeps_shell_name_without_agent_session_metadata,
    test_completion_notification_omits_bead_display_for_ordinary_agent,
    test_deferred_epic_completion_names_owning_agent_session,
    test_failure_error_report_notification_adds_bead_display,
    test_failure_error_report_notification_names_owning_agent_session,
    test_success_completion_notification_names_owning_agent_session,
)

__test__ = False

__all__ = [
    "test_adopted_receipt_produces_no_held_note",
    "test_completion_notification_adds_bead_display_for_bead_agent",
    "test_completion_notification_bead_display_uses_agent_session_name",
    "test_completion_notification_does_not_truncate_dotted_standalone_name",
    "test_completion_notification_keeps_shell_name_without_agent_session_metadata",
    "test_completion_notification_omits_bead_display_for_ordinary_agent",
    "test_completion_notification_omits_empty_output_variables",
    "test_completion_notification_reads_commit_result_without_step_output",
    "test_completion_notification_surfaces_terminal_retention_record",
    "test_completion_notification_uses_full_commit_result_message",
    "test_deferred_epic_completion_names_owning_agent_session",
    "test_epic_approved_classifies_as_runner_success",
    "test_epic_approved_without_publication_error_has_no_degraded_note",
    "test_failed_notification_includes_held_workspace_recovery",
    "test_failed_notification_names_held_staged_handoff",
    "test_failure_completion_notification_is_not_tagged_done",
    "test_failure_error_report_notification_adds_bead_display",
    "test_failure_error_report_notification_includes_output_variables",
    "test_failure_error_report_notification_includes_runtime",
    "test_failure_error_report_notification_names_owning_agent_session",
    "test_gated_suppresses_completion_notification",
    "test_held_staged_handoff_note_names_exact_readopt_command",
    "test_held_staged_handoff_without_recovery_evidence_prompts_salvage",
    "test_hidden_agent_failure_still_silent",
    "test_hidden_agent_forwards_silent_true",
    "test_malformed_receipt_produces_malformed_held_note",
    "test_monitored_suppresses_completion_notification",
    "test_no_staged_files_produces_no_held_note",
    "test_plan_rejected_classifies_as_runner_success",
    "test_plan_rejected_suppresses_completion_notification",
    "test_real_failure_stays_runner_failure",
    "test_sdd_publication_error_rides_deferred_epic_completion",
    "test_success_completion_notification_includes_output_variables",
    "test_success_completion_notification_includes_runtime",
    "test_success_completion_notification_names_owning_agent_session",
    "test_success_completion_notification_tags_done",
    "test_visible_agent_forwards_silent_false",
]
