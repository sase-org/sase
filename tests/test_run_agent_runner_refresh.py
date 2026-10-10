"""Tests for refreshing stale runner code after dependency waits.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_run_agent_runner_refresh_handoff import (
    test_changed_identity_reexecs_original_argv,
    test_exec_failure_continues_without_refresh_guard_or_prompt_file,
    test_exec_failure_restores_prior_planned_name,
    test_prompt_rewrite_failure_skips_refresh,
    test_refresh_handoff_drops_stale_planned_name_without_current_ownership,
    test_refresh_handoff_preserves_current_agent_name,
    test_refresh_is_inert_without_all_preconditions,
    test_refresh_path_imports_no_new_sase_modules,
    test_refreshed_guard_prevents_loop_and_is_not_inherited,
)
from tests.test_run_agent_runner_refresh_identity import (
    test_source_code_identity_is_inert_without_git_metadata,
    test_source_code_identity_tracks_head_changes,
)
from tests.test_run_agent_runner_refresh_macros import (
    test_refresh_exec_failure_restores_local_macros_env,
    test_refresh_exec_failure_restores_prior_local_macros_value,
    test_refresh_leaves_local_macros_env_untouched_when_empty,
    test_refresh_rematerializes_local_macros_for_exec,
    test_refresh_serialization_failure_skips_refresh,
)
from tests.test_run_agent_runner_refresh_reconcile import (
    test_non_refreshed_pass_leaves_prompt_unreconciled,
    test_refresh_local_macros_boundary_replay,
    test_refreshed_pass_reconcile_keeps_wait_time_auto_toggle,
)

__test__ = False

__all__ = [
    "test_changed_identity_reexecs_original_argv",
    "test_exec_failure_continues_without_refresh_guard_or_prompt_file",
    "test_exec_failure_restores_prior_planned_name",
    "test_non_refreshed_pass_leaves_prompt_unreconciled",
    "test_prompt_rewrite_failure_skips_refresh",
    "test_refresh_exec_failure_restores_local_macros_env",
    "test_refresh_exec_failure_restores_prior_local_macros_value",
    "test_refresh_handoff_drops_stale_planned_name_without_current_ownership",
    "test_refresh_handoff_preserves_current_agent_name",
    "test_refresh_is_inert_without_all_preconditions",
    "test_refresh_leaves_local_macros_env_untouched_when_empty",
    "test_refresh_local_macros_boundary_replay",
    "test_refresh_path_imports_no_new_sase_modules",
    "test_refresh_rematerializes_local_macros_for_exec",
    "test_refresh_serialization_failure_skips_refresh",
    "test_refreshed_guard_prevents_loop_and_is_not_inherited",
    "test_refreshed_pass_reconcile_keeps_wait_time_auto_toggle",
    "test_source_code_identity_is_inert_without_git_metadata",
    "test_source_code_identity_tracks_head_changes",
]
