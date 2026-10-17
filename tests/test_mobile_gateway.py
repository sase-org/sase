"""Tests for the SASE mobile gateway Python integration.

The implementation lives in private modules while this facade preserves the original
pytest collection and import path.
"""

from __future__ import annotations

from tests._test_mobile_gateway_config import (
    test_load_mobile_gateway_config_defaults,
    test_load_mobile_gateway_config_normalizes_values,
    test_prepare_launch_builds_default_loopback_argv,
    test_prepare_launch_includes_non_secret_push_settings,
    test_prepare_launch_includes_state_dir_and_cli_overrides,
    test_prepare_launch_missing_binary_error_text,
    test_prepare_launch_propagates_non_loopback_opt_in,
    test_prepare_launch_rejects_non_loopback_without_opt_in,
    test_prepare_service_launch_uses_direct_gateway_argv,
    test_resolve_gateway_command_checks_active_python_environment,
)
from tests._test_mobile_gateway_pairing import (
    test_run_mobile_gateway_pair_issues_owner_local_challenge,
    test_run_mobile_gateway_pair_passes_cli_state_dir,
    test_run_mobile_gateway_pair_rejects_old_gateway_without_issuing,
    test_run_mobile_gateway_pair_uses_config_state_dir,
    test_run_mobile_gateway_pair_wraps_missing_binding,
)
from tests._test_mobile_gateway_parser import (
    test_parser_accepts_legacy_mobile_helper_bridge_catalog,
    test_parser_accepts_mobile_agent_bridge_fork_agent,
    test_parser_accepts_mobile_agent_bridge_kill_agent,
    test_parser_accepts_mobile_agent_bridge_launch_image,
    test_parser_accepts_mobile_agent_bridge_launch_text,
    test_parser_accepts_mobile_agent_bridge_retry_agent,
    test_parser_accepts_mobile_gateway_pair,
    test_parser_accepts_mobile_gateway_start,
    test_parser_accepts_mobile_helper_bridge_bead_operations,
    test_parser_accepts_mobile_helper_bridge_macro_catalog,
    test_parser_accepts_mobile_helper_bridge_patch_tags,
    test_parser_accepts_mobile_helper_bridge_update_start,
    test_parser_accepts_mobile_helper_bridge_update_status,
    test_parser_accepts_mobile_notification_bridge,
)
from tests._test_mobile_gateway_start import (
    test_run_mobile_gateway_start_delegates_to_service_host,
    test_run_mobile_gateway_start_foreground_lifecycle,
    test_service_host_owns_gateway_follows_the_configured_entry,
    test_service_host_owns_gateway_is_false_when_service_apis_fail,
)

__all__ = [
    "test_load_mobile_gateway_config_defaults",
    "test_load_mobile_gateway_config_normalizes_values",
    "test_parser_accepts_legacy_mobile_helper_bridge_catalog",
    "test_parser_accepts_mobile_agent_bridge_fork_agent",
    "test_parser_accepts_mobile_agent_bridge_kill_agent",
    "test_parser_accepts_mobile_agent_bridge_launch_image",
    "test_parser_accepts_mobile_agent_bridge_launch_text",
    "test_parser_accepts_mobile_agent_bridge_retry_agent",
    "test_parser_accepts_mobile_gateway_pair",
    "test_parser_accepts_mobile_gateway_start",
    "test_parser_accepts_mobile_helper_bridge_bead_operations",
    "test_parser_accepts_mobile_helper_bridge_macro_catalog",
    "test_parser_accepts_mobile_helper_bridge_patch_tags",
    "test_parser_accepts_mobile_helper_bridge_update_start",
    "test_parser_accepts_mobile_helper_bridge_update_status",
    "test_parser_accepts_mobile_notification_bridge",
    "test_prepare_launch_builds_default_loopback_argv",
    "test_prepare_launch_includes_non_secret_push_settings",
    "test_prepare_launch_includes_state_dir_and_cli_overrides",
    "test_prepare_launch_missing_binary_error_text",
    "test_prepare_launch_propagates_non_loopback_opt_in",
    "test_prepare_launch_rejects_non_loopback_without_opt_in",
    "test_prepare_service_launch_uses_direct_gateway_argv",
    "test_resolve_gateway_command_checks_active_python_environment",
    "test_run_mobile_gateway_pair_issues_owner_local_challenge",
    "test_run_mobile_gateway_pair_passes_cli_state_dir",
    "test_run_mobile_gateway_pair_rejects_old_gateway_without_issuing",
    "test_run_mobile_gateway_pair_uses_config_state_dir",
    "test_run_mobile_gateway_pair_wraps_missing_binding",
    "test_run_mobile_gateway_start_delegates_to_service_host",
    "test_run_mobile_gateway_start_foreground_lifecycle",
    "test_service_host_owns_gateway_follows_the_configured_entry",
    "test_service_host_owns_gateway_is_false_when_service_apis_fail",
]
