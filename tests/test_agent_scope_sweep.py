"""Unit tests for the agent-scope sweep (runner teardown).

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_agent_scope_sweep_execute import (
    test_execute_grace_escalation_term_then_kill,
    test_execute_identity_pinning_skips_recycled_pid,
    test_execute_late_arrival_gets_sigkill_directly,
    test_execute_real_signal_only_targets_created_pids,
)
from tests.test_agent_scope_sweep_own import (
    test__own_agent_scope_gates,
    test_sweep_never_raises,
    test_sweep_prints_summary_line,
    test_sweep_skipped_outside_scope,
)
from tests.test_agent_scope_sweep_plan import (
    test_invalid_spare_regex_is_ignored,
    test_is_agent_runner_first_three_argv,
    test_protect_root_descendants_survive,
    test_protect_root_pid_form,
    test_read_scope_members_skips_zombie_and_unreadable,
    test_spare_by_comm_and_cmdline_plus_descendants,
)
from tests.test_agent_scope_sweep_runner import (
    test_exec_loop_no_sweep_for_single_turn,
    test_exec_loop_sweeps_only_from_second_iteration,
    test_main_sweep_failure_still_cleans_up,
    test_main_sweeps_before_shutdown,
    test_main_sweeps_on_agent_exception,
    test_main_sweeps_on_plain_system_exit,
    test_main_sweeps_on_user_kill,
)

__test__ = False

__all__ = [
    "test__own_agent_scope_gates",
    "test_exec_loop_no_sweep_for_single_turn",
    "test_exec_loop_sweeps_only_from_second_iteration",
    "test_execute_grace_escalation_term_then_kill",
    "test_execute_identity_pinning_skips_recycled_pid",
    "test_execute_late_arrival_gets_sigkill_directly",
    "test_execute_real_signal_only_targets_created_pids",
    "test_invalid_spare_regex_is_ignored",
    "test_is_agent_runner_first_three_argv",
    "test_main_sweep_failure_still_cleans_up",
    "test_main_sweeps_before_shutdown",
    "test_main_sweeps_on_agent_exception",
    "test_main_sweeps_on_plain_system_exit",
    "test_main_sweeps_on_user_kill",
    "test_protect_root_descendants_survive",
    "test_protect_root_pid_form",
    "test_read_scope_members_skips_zombie_and_unreadable",
    "test_spare_by_comm_and_cmdline_plus_descendants",
    "test_sweep_never_raises",
    "test_sweep_prints_summary_line",
    "test_sweep_skipped_outside_scope",
]
