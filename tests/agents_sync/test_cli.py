"""Compatibility facade for the split agent CLI tests."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_TEST_MODULES = {
    "test_parser_accepts_repeatable_project_and_check_refresh": "test_cli_parser",
    "test_parser_rejects_refresh_without_check": "test_cli_parser",
    "test_parser_accepts_retry_quarantined_only_for_full_sync": "test_cli_parser",
    "test_parser_accepts_retry_retired_with_project_and_quarantine_combo": "test_cli_parser",
    "test_parser_accepts_bounded_retry_aliases_and_repeated_error_classes": "test_cli_parser",
    "test_parser_accepts_retry_key_alias_and_full_outbox_identity": "test_cli_parser",
    "test_parser_rejects_invalid_bounded_retry_options": "test_cli_parser",
    "test_parser_rejects_retry_retired_without_project": "test_cli_parser",
    "test_parser_rejects_retry_retired_with_incompatible_modes": "test_cli_parser",
    "test_parser_accepts_repair_digests_flag": "test_cli_parser",
    "test_parser_accepts_repair_manifest_flag": "test_cli_parser",
    "test_parser_accepts_drop_retired_only_for_full_sync": "test_cli_parser",
    "test_sync_help_distinguishes_full_cached_and_refresh_modes": "test_cli_parser",
    "test_agent_help_keeps_bare_list_delegation_and_sorted_commands": "test_cli_parser",
    "test_check_json_is_stable_and_errors_exit_nonzero": "test_cli_sync",
    "test_mutating_sync_json_allows_benign_skips": "test_cli_sync",
    "test_mutating_sync_forwards_drop_retired_and_renders_its_report": "test_cli_sync",
    "test_mutating_sync_forwards_retry_retired": "test_cli_sync",
    "test_mutating_sync_forwards_bounded_retry_options": "test_cli_sync",
    "test_mutating_sync_forwards_retry_key": "test_cli_sync",
    "test_mutating_sync_pretty_table_reports_counts_and_result": "test_cli_sync",
    "test_repair_digests_dispatches_before_check_and_reports_diagnostics": "test_cli_sync",
    "test_repair_manifest_dispatches_before_check_and_reports_diagnostics": "test_cli_sync",
    "test_names_bare_usage_lists_both_subcommands": "test_cli_names",
    "test_names_purge_local_state_parser_accepts_apply_and_json": "test_cli_names",
    "test_names_purge_local_state_cli_dispatches_and_reports_json": "test_cli_names",
    "test_parser_accepts_repair_states_flags": "test_cli_names",
    "test_parser_rejects_repair_states_combinations": "test_cli_names",
    "test_repair_states_dispatches_and_reports_json": "test_cli_names",
}

__all__ = tuple(_TEST_MODULES)


def __getattr__(name: str) -> object:
    module_name = _TEST_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module: ModuleType = import_module(f".{module_name}", __package__)
    return getattr(module, name)
