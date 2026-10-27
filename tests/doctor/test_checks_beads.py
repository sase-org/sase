"""Tests for Phase 4 doctor bead checks.

The implementation lives in focused modules; this facade preserves the original
pytest module path and its public test names.
"""

from __future__ import annotations

from tests.doctor._checks_beads_project import (
    test_project_beads_skips_when_store_is_absent,
    test_project_beads_adapts_warning_messages,
    test_project_beads_prefers_resolved_local_store,
    test_project_beads_discovers_split_sidecar,
    test_project_beads_summary_counts_claimed_issues,
    test_project_beads_degrades_when_git_is_unavailable,
    test_project_beads_warns_about_claim_without_resolvable_artifact,
)

from tests.doctor._checks_beads_agents import (
    test_project_beads_resolves_claim_owner_from_any_artifact,
    test_project_beads_warns_about_live_agent_whose_bead_is_unclaimed,
    test_project_beads_warns_about_claim_whose_owner_died,
    test_project_beads_does_not_use_the_old_in_progress_gone_warning,
    test_project_beads_warns_about_stranded_beads,
    test_project_beads_warns_about_recovered_unassigned_task,
    test_project_beads_stays_silent_for_a_live_in_progress_owner,
    test_project_beads_ignores_promoted_and_dead_bead_owners,
)

from tests.doctor._checks_beads_dependencies import (
    test_project_beads_warns_about_dangling_dependency_edges,
    test_project_beads_ignores_satisfied_dependency_edges,
)

from tests.doctor._checks_beads_task_types import (
    test_check_task_types_ok_when_catalog_is_clean,
    test_check_task_types_reports_errors_and_warnings,
)

__all__ = [
    "test_project_beads_skips_when_store_is_absent",
    "test_project_beads_adapts_warning_messages",
    "test_project_beads_prefers_resolved_local_store",
    "test_project_beads_discovers_split_sidecar",
    "test_project_beads_summary_counts_claimed_issues",
    "test_project_beads_degrades_when_git_is_unavailable",
    "test_project_beads_warns_about_claim_without_resolvable_artifact",
    "test_project_beads_resolves_claim_owner_from_any_artifact",
    "test_project_beads_warns_about_live_agent_whose_bead_is_unclaimed",
    "test_project_beads_warns_about_claim_whose_owner_died",
    "test_project_beads_does_not_use_the_old_in_progress_gone_warning",
    "test_project_beads_warns_about_stranded_beads",
    "test_project_beads_warns_about_recovered_unassigned_task",
    "test_project_beads_stays_silent_for_a_live_in_progress_owner",
    "test_project_beads_ignores_promoted_and_dead_bead_owners",
    "test_project_beads_warns_about_dangling_dependency_edges",
    "test_project_beads_ignores_satisfied_dependency_edges",
    "test_check_task_types_ok_when_catalog_is_clean",
    "test_check_task_types_reports_errors_and_warnings",
]
