"""Run-agent wait dependency helper tests.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_run_agent_wait_deps_fork_source import (
    test_fork_source_wait_binds_exact_agent_not_newer_namesake,
    test_fork_source_wait_keeps_waiting_for_live_clan_member,
    test_fork_source_wait_releases_failed_agent_dependency,
    test_fork_source_wait_releases_failed_agent_session_generation,
    test_fork_source_wait_releases_terminal_clan_generation,
    test_fork_source_wait_resolves_proc_only_when_terminal,
)
from tests.test_run_agent_wait_deps_initial import (
    test_initial_wait_release_matches_terminal_outcome_semantics,
    test_initial_wait_release_routes_full_bead_wait_to_owner_project,
    test_initial_wait_release_uses_cross_project_stored_job_identity,
    test_mark_bead_wait_sync_hint_contains_hint_failures,
    test_mark_bead_wait_sync_hint_honors_off_mode,
    test_mark_bead_wait_sync_hint_marks_the_beads_role,
    test_runner_confirmation_rejects_stale_agent_session_then_accepts_complete_agent_session,
    test_runner_fallback_confirmation_failure_warns_and_stays_parked,
    test_runner_fallback_index_failure_warns_and_stays_parked,
)
from tests.test_run_agent_wait_deps_waiting_marker import (
    test_waiting_marker_dependencies_resolved_matches_terminal_outcome_semantics,
    test_waiting_marker_fallback_resolves_non_monitor_completed_workflow_without_done,
    test_waiting_marker_fallback_waits_for_settled_gate_without_terminal_outcome,
    test_waiting_marker_fallback_waits_for_settled_monitor_without_terminal_outcome,
)

__test__ = False

__all__ = [
    "test_fork_source_wait_binds_exact_agent_not_newer_namesake",
    "test_fork_source_wait_keeps_waiting_for_live_clan_member",
    "test_fork_source_wait_releases_failed_agent_dependency",
    "test_fork_source_wait_releases_failed_agent_session_generation",
    "test_fork_source_wait_releases_terminal_clan_generation",
    "test_fork_source_wait_resolves_proc_only_when_terminal",
    "test_initial_wait_release_matches_terminal_outcome_semantics",
    "test_initial_wait_release_routes_full_bead_wait_to_owner_project",
    "test_initial_wait_release_uses_cross_project_stored_job_identity",
    "test_mark_bead_wait_sync_hint_contains_hint_failures",
    "test_mark_bead_wait_sync_hint_honors_off_mode",
    "test_mark_bead_wait_sync_hint_marks_the_beads_role",
    "test_runner_confirmation_rejects_stale_agent_session_then_accepts_complete_agent_session",
    "test_runner_fallback_confirmation_failure_warns_and_stays_parked",
    "test_runner_fallback_index_failure_warns_and_stays_parked",
    "test_waiting_marker_dependencies_resolved_matches_terminal_outcome_semantics",
    "test_waiting_marker_fallback_resolves_non_monitor_completed_workflow_without_done",
    "test_waiting_marker_fallback_waits_for_settled_gate_without_terminal_outcome",
    "test_waiting_marker_fallback_waits_for_settled_monitor_without_terminal_outcome",
]
