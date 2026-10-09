"""Parser help and typed results for durable domain commands.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.main.test_ops_commands_agent_drain import (
    test_agent_drain_automatic_move_failed_still_fails,
    test_agent_drain_automatic_not_disabled_is_successful_noop,
    test_agent_drain_automatic_nothing_to_drain_is_successful_noop,
    test_agent_drain_non_automatic_nothing_to_drain_stays_failed,
    test_agent_drain_operation_owns_notification_when_payload_says_notify,
    test_agent_drain_operation_without_notify_payload_skips_notification,
    test_agent_drain_operation_writes_result_and_preserves_exit_code,
)

from tests.main.test_ops_commands_agent_persist import (
    test_agent_persist_cleanup_applies_json_identities,
    test_agent_persist_directive_applies_prompt_mutation,
    test_agent_persist_directive_uses_request_sidecar,
)

from tests.main.test_ops_commands_help import (
    test_bead_apply_status_help_is_documented,
    test_notify_and_agent_operation_help,
    test_patch_help_lists_operation_commands_sorted,
)

from tests.main.test_ops_commands_notify import (
    test_notify_apply_state_many_read_reaches_tab_scoped_store,
    test_notify_apply_state_many_undismiss_reaches_bulk_store,
    test_notify_apply_state_success_and_failure,
    test_notify_apply_state_undismiss_reaches_store,
)

from tests.main.test_ops_commands_patch_bead import (
    test_bead_apply_status_success_and_failure,
    test_patch_status_success_and_failure_results,
    test_plugin_monitor_and_run_result_helpers,
)

__test__ = False

__all__ = [
    "test_agent_drain_automatic_move_failed_still_fails",
    "test_agent_drain_automatic_not_disabled_is_successful_noop",
    "test_agent_drain_automatic_nothing_to_drain_is_successful_noop",
    "test_agent_drain_non_automatic_nothing_to_drain_stays_failed",
    "test_agent_drain_operation_owns_notification_when_payload_says_notify",
    "test_agent_drain_operation_without_notify_payload_skips_notification",
    "test_agent_drain_operation_writes_result_and_preserves_exit_code",
    "test_agent_persist_cleanup_applies_json_identities",
    "test_agent_persist_directive_applies_prompt_mutation",
    "test_agent_persist_directive_uses_request_sidecar",
    "test_bead_apply_status_help_is_documented",
    "test_bead_apply_status_success_and_failure",
    "test_notify_and_agent_operation_help",
    "test_notify_apply_state_many_read_reaches_tab_scoped_store",
    "test_notify_apply_state_many_undismiss_reaches_bulk_store",
    "test_notify_apply_state_success_and_failure",
    "test_notify_apply_state_undismiss_reaches_store",
    "test_patch_help_lists_operation_commands_sorted",
    "test_patch_status_success_and_failure_results",
    "test_plugin_monitor_and_run_result_helpers",
]
