"""CLI contract tests for project onboarding preview and apply.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.project_onboarding.test_cli_add import (
    test_check_blocker_returns_one_without_calling_apply,
    test_durable_request_must_match_argv_target,
    test_explicit_agent_setup_refusal_uses_exit_two,
    test_fake_provider_cli_check_emits_one_document_and_performs_no_writes,
    test_json_apply_stream_and_result_file_share_terminal_event,
    test_non_tty_refuses_without_yes_and_does_not_apply,
    test_parser_registers_sorted_add_options_and_rejects_setup_conflict,
    test_tty_success_offers_init_and_records_its_terminal_result,
)
from tests.project_onboarding.test_cli_bare_git import (
    test_bare_git_create_end_to_end,
    test_bare_git_create_honors_custom_bare_dir,
    test_bare_git_create_resumes_after_checkout_failure_with_custom_bare_dir,
)
from tests.project_onboarding.test_cli_create import (
    test_create_apply_refuses_agent_with_gate_message,
    test_create_bypass_prints_reason,
    test_create_check_is_available_to_agents,
    test_create_gate_option_allows_apply,
    test_create_option_values_equal_to_transport_flags_are_data,
    test_create_sugar_overlays_dash_o_options,
    test_parser_registers_sorted_create_options_and_rejects_bad_option,
)

__test__ = False

__all__ = [
    "test_bare_git_create_end_to_end",
    "test_bare_git_create_honors_custom_bare_dir",
    "test_bare_git_create_resumes_after_checkout_failure_with_custom_bare_dir",
    "test_check_blocker_returns_one_without_calling_apply",
    "test_create_apply_refuses_agent_with_gate_message",
    "test_create_bypass_prints_reason",
    "test_create_check_is_available_to_agents",
    "test_create_gate_option_allows_apply",
    "test_create_option_values_equal_to_transport_flags_are_data",
    "test_create_sugar_overlays_dash_o_options",
    "test_durable_request_must_match_argv_target",
    "test_explicit_agent_setup_refusal_uses_exit_two",
    "test_fake_provider_cli_check_emits_one_document_and_performs_no_writes",
    "test_json_apply_stream_and_result_file_share_terminal_event",
    "test_non_tty_refuses_without_yes_and_does_not_apply",
    "test_parser_registers_sorted_add_options_and_rejects_setup_conflict",
    "test_parser_registers_sorted_create_options_and_rejects_bad_option",
    "test_tty_success_offers_init_and_records_its_terminal_result",
]
