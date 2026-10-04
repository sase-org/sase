"""Tests for escaping service-owned cgroups when launching detached work.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_detach_scope_bootstrap import (
    test_monitor_supervisor_bootstrap_uses_detach_scope,
    test_monitor_supervisor_bootstrap_uses_pid_file_for_systemd_scope,
    test_proc_supervisor_bootstrap_uses_detach_scope,
    test_proc_supervisor_bootstrap_uses_pid_file_for_systemd_scope,
)
from tests.test_detach_scope_command import (
    test_detach_scope_disable_env_wins_over_user_manager,
    test_detach_scope_escapes_from_tmux_scope_via_user_manager,
    test_detach_scope_escapes_via_runtime_socket,
    test_detach_scope_honors_disable_env,
    test_detach_scope_ignores_other_uid_user_manager,
    test_detach_scope_noops_outside_user_manager,
    test_detach_scope_noops_without_systemd_run,
    test_detach_scope_oom_policy_gated_by_version,
    test_detach_scope_uses_setsid_on_macos,
    test_detach_scope_wraps_inside_sase_cgroup,
    test_process_systemd_unit_parses_scope_and_service,
    test_sase_owned_systemd_unit_matrix,
    test_systemd_run_version_parses_first_line,
)
from tests.test_detach_scope_live import (
    test_live_scope_pid_unchanged_through_detach,
    test_live_scope_preserves_lock_fd_through_detach,
    test_live_scope_reports_oom_policy_continue,
    test_live_systemd_scope_changes_child_cgroup_when_running_from_sase_unit,
)

__test__ = False

__all__ = [
    "test_detach_scope_disable_env_wins_over_user_manager",
    "test_detach_scope_escapes_from_tmux_scope_via_user_manager",
    "test_detach_scope_escapes_via_runtime_socket",
    "test_detach_scope_honors_disable_env",
    "test_detach_scope_ignores_other_uid_user_manager",
    "test_detach_scope_noops_outside_user_manager",
    "test_detach_scope_noops_without_systemd_run",
    "test_detach_scope_oom_policy_gated_by_version",
    "test_detach_scope_uses_setsid_on_macos",
    "test_detach_scope_wraps_inside_sase_cgroup",
    "test_live_scope_pid_unchanged_through_detach",
    "test_live_scope_preserves_lock_fd_through_detach",
    "test_live_scope_reports_oom_policy_continue",
    "test_live_systemd_scope_changes_child_cgroup_when_running_from_sase_unit",
    "test_monitor_supervisor_bootstrap_uses_detach_scope",
    "test_monitor_supervisor_bootstrap_uses_pid_file_for_systemd_scope",
    "test_proc_supervisor_bootstrap_uses_detach_scope",
    "test_proc_supervisor_bootstrap_uses_pid_file_for_systemd_scope",
    "test_process_systemd_unit_parses_scope_and_service",
    "test_sase_owned_systemd_unit_matrix",
    "test_systemd_run_version_parses_first_line",
]
