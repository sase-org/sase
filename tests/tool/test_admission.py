"""In-process tests for the pre-spawn host admission gate.

The test implementations live in private modules to keep this compatibility
import path small while preserving pytest collection and public test names.
"""

from tests.tool._admission_exemptions import (
    test_unset_config_makes_no_admission_call_and_writes_no_record,
    test_uncapped_tool_and_adhoc_runs_are_never_limited,
    test_nested_run_inside_a_live_parent_is_exempt,
    test_settled_inherited_parent_is_not_nesting,
    test_agent_with_cleared_inherited_parent_queues_as_a_new_root,
    test_agent_command_child_keeps_its_parent_and_skips_admission,
    test_join_worker_takes_no_slot,
    test_unrecorded_run_falls_open_without_a_core_call,
    test_invalid_config_falls_open_naming_the_field,
    test_missing_binding_falls_open_at_once,
    test_persistent_store_errors_fall_open_after_the_grace,
)

from tests.tool._admission_wait import (
    test_waiter_prints_counts_then_the_grant_and_records_the_wait,
    test_immediate_admission_prints_nothing,
    test_max_wait_admits_over_the_limit,
    test_force_settled_stops_before_the_child_runs,
    test_force_not_found_falls_open_and_recovers_unavailable_evidence,
    test_transient_force_error_retries_until_max_wait_is_confirmed,
    test_force_store_error_falls_open_and_recovers_before_child_settlement,
    test_poll_failure_after_entry_recovers_the_bypass_at_a_later_write,
    test_unrecovered_bypass_is_named_in_settlement_diagnostics,
    test_stop_or_timeout_during_force_retry_does_not_start_child,
    test_dead_holder_is_reconciled_and_frees_its_slot,
)

from tests.tool._admission_settlement import (
    test_stopped_waiter_settles_without_running_and_is_abandoned,
    test_sigterm_while_waiting_settles_signaled,
    test_admitted_run_executes_its_child_once,
)

__all__ = [
    "test_unset_config_makes_no_admission_call_and_writes_no_record",
    "test_uncapped_tool_and_adhoc_runs_are_never_limited",
    "test_nested_run_inside_a_live_parent_is_exempt",
    "test_settled_inherited_parent_is_not_nesting",
    "test_agent_with_cleared_inherited_parent_queues_as_a_new_root",
    "test_agent_command_child_keeps_its_parent_and_skips_admission",
    "test_join_worker_takes_no_slot",
    "test_unrecorded_run_falls_open_without_a_core_call",
    "test_invalid_config_falls_open_naming_the_field",
    "test_missing_binding_falls_open_at_once",
    "test_persistent_store_errors_fall_open_after_the_grace",
    "test_waiter_prints_counts_then_the_grant_and_records_the_wait",
    "test_immediate_admission_prints_nothing",
    "test_max_wait_admits_over_the_limit",
    "test_force_settled_stops_before_the_child_runs",
    "test_force_not_found_falls_open_and_recovers_unavailable_evidence",
    "test_transient_force_error_retries_until_max_wait_is_confirmed",
    "test_force_store_error_falls_open_and_recovers_before_child_settlement",
    "test_poll_failure_after_entry_recovers_the_bypass_at_a_later_write",
    "test_unrecovered_bypass_is_named_in_settlement_diagnostics",
    "test_stop_or_timeout_during_force_retry_does_not_start_child",
    "test_dead_holder_is_reconciled_and_frees_its_slot",
    "test_stopped_waiter_settles_without_running_and_is_abandoned",
    "test_sigterm_while_waiting_settles_signaled",
    "test_admitted_run_executes_its_child_once",
]
