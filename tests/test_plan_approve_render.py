"""Human output and exit codes for ``sase plan approve`` under ``NO_COLOR``.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_plan_approve_render_direct import (
    test_approval_error_renders_code_specific_hint,
    test_approval_error_without_recovery_hint_is_one_line,
    test_direct_agent_session_card,
    test_direct_approve_kind_is_not_labelled_committed,
    test_direct_card_prints_best_effort_warnings,
    test_direct_commit_only_card_launches_no_coder,
    test_direct_dry_run_card_agent_session_with_gate,
    test_direct_dry_run_card_standalone,
    test_direct_gate_answered_concurrently_card_for_commit_needs_no_recovery,
    test_direct_gate_answered_concurrently_card_for_tale,
    test_direct_partial_failure_card_gives_recovery_command,
    test_direct_partial_failure_recovery_command_survives_multiline_prompt,
    test_direct_standalone_card_falls_back_to_pid_without_agent_name,
    test_direct_standalone_card_gives_reason,
    test_refusal_does_not_double_prefix_or_repeat_hints,
    test_refusal_prints_header_details_and_hints_to_stderr,
)
from tests.test_plan_approve_render_gate import (
    test_gate_dry_run_card_changes_nothing,
    test_gate_epic_approval_shows_monitor_launch,
    test_gate_epic_approval_shows_proc_launch,
    test_gate_success_card_names_coder_and_gate,
    test_gate_success_reports_coder_launch_failure,
    test_gate_success_without_result_fields_says_shell_launches_next,
)
from tests.test_plan_approve_render_handler import (
    test_handler_allows_dry_run_from_inside_an_agent,
    test_handler_dry_run_exits_zero_without_executing,
    test_handler_exits_one_when_coder_launch_failed,
    test_handler_exits_one_when_tale_gate_was_answered_concurrently,
    test_handler_exits_two_for_refusal_raised_during_execution,
    test_handler_exits_two_for_upfront_refusal,
    test_handler_exits_zero_for_complete_direct_approval,
    test_handler_exits_zero_when_commit_gate_was_answered_concurrently,
    test_handler_refuses_direct_execution_from_inside_an_agent,
)
from tests.test_plan_approve_render_recovery import (
    test_already_implemented_refusal_offers_run_anyway,
    test_coder_running_refusal_renders_once,
    test_recovery_card,
    test_recovery_card_without_prior_coder,
    test_recovery_dry_run,
    test_recovery_launch_failure_card,
)

__test__ = False

__all__ = [
    "test_already_implemented_refusal_offers_run_anyway",
    "test_approval_error_renders_code_specific_hint",
    "test_approval_error_without_recovery_hint_is_one_line",
    "test_coder_running_refusal_renders_once",
    "test_direct_agent_session_card",
    "test_direct_approve_kind_is_not_labelled_committed",
    "test_direct_card_prints_best_effort_warnings",
    "test_direct_commit_only_card_launches_no_coder",
    "test_direct_dry_run_card_agent_session_with_gate",
    "test_direct_dry_run_card_standalone",
    "test_direct_gate_answered_concurrently_card_for_commit_needs_no_recovery",
    "test_direct_gate_answered_concurrently_card_for_tale",
    "test_direct_partial_failure_card_gives_recovery_command",
    "test_direct_partial_failure_recovery_command_survives_multiline_prompt",
    "test_direct_standalone_card_falls_back_to_pid_without_agent_name",
    "test_direct_standalone_card_gives_reason",
    "test_gate_dry_run_card_changes_nothing",
    "test_gate_epic_approval_shows_monitor_launch",
    "test_gate_epic_approval_shows_proc_launch",
    "test_gate_success_card_names_coder_and_gate",
    "test_gate_success_reports_coder_launch_failure",
    "test_gate_success_without_result_fields_says_shell_launches_next",
    "test_handler_allows_dry_run_from_inside_an_agent",
    "test_handler_dry_run_exits_zero_without_executing",
    "test_handler_exits_one_when_coder_launch_failed",
    "test_handler_exits_one_when_tale_gate_was_answered_concurrently",
    "test_handler_exits_two_for_refusal_raised_during_execution",
    "test_handler_exits_two_for_upfront_refusal",
    "test_handler_exits_zero_for_complete_direct_approval",
    "test_handler_exits_zero_when_commit_gate_was_answered_concurrently",
    "test_handler_refuses_direct_execution_from_inside_an_agent",
    "test_recovery_card",
    "test_recovery_card_without_prior_coder",
    "test_recovery_dry_run",
    "test_recovery_launch_failure_card",
    "test_refusal_does_not_double_prefix_or_repeat_hints",
    "test_refusal_prints_header_details_and_hints_to_stderr",
]
