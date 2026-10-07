"""Generic primary-sidecar auto-sync chop tests.

This module is a facade preserving the original import path. The tests
now live in :mod:`tests.test_axe_chop_sidecar_auto_sync_targets`,
:mod:`tests.test_axe_chop_sidecar_auto_sync_backoff`, and
:mod:`tests.test_axe_chop_sidecar_auto_sync_maintenance`; shared fixtures
live in :mod:`tests._axe_chop_sidecar_auto_sync_support`. Only public
names are re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

from tests.test_axe_chop_sidecar_auto_sync_backoff import (
    test_corrupt_schedule_state_is_treated_as_empty,
    test_exhausted_work_budget_defers_remaining_targets,
    test_failure_like_status_backs_off_exponentially,
    test_hinted_role_bypasses_backoff,
    test_stale_schedule_entries_are_pruned_for_deconfigured_roles,
    test_successful_sync_defers_maintenance_when_work_budget_is_exhausted,
    test_unhinted_role_backstops_then_skips_within_interval,
)
from tests.test_axe_chop_sidecar_auto_sync_maintenance import (
    TestProjectsWithLiveBeadWaits,
    test_prune_leg_delegates_to_sync_log_retention,
    test_run_skips_maintenance_legs_when_budget_exhausted,
    test_run_visits_hidden_clones_for_each_project,
    test_successful_sync_runs_sidecar_maintenance,
)
from tests.test_axe_chop_sidecar_auto_sync_targets import (
    test_bead_refresh_mode_off_skips_the_live_wait_scan,
    test_hinted_role_refreshes_and_clears_its_hint,
    test_live_bead_wait_does_not_duplicate_an_already_opted_in_beads_role,
    test_live_bead_wait_forces_a_beads_target_without_auto_sync_opt_in,
    test_multiple_roles_in_one_project_are_all_attempted,
    test_no_auto_sync_roles_short_circuits,
)

__all__ = [
    "TestProjectsWithLiveBeadWaits",
    "test_bead_refresh_mode_off_skips_the_live_wait_scan",
    "test_corrupt_schedule_state_is_treated_as_empty",
    "test_exhausted_work_budget_defers_remaining_targets",
    "test_failure_like_status_backs_off_exponentially",
    "test_hinted_role_bypasses_backoff",
    "test_hinted_role_refreshes_and_clears_its_hint",
    "test_live_bead_wait_does_not_duplicate_an_already_opted_in_beads_role",
    "test_live_bead_wait_forces_a_beads_target_without_auto_sync_opt_in",
    "test_multiple_roles_in_one_project_are_all_attempted",
    "test_no_auto_sync_roles_short_circuits",
    "test_prune_leg_delegates_to_sync_log_retention",
    "test_run_skips_maintenance_legs_when_budget_exhausted",
    "test_run_visits_hidden_clones_for_each_project",
    "test_stale_schedule_entries_are_pruned_for_deconfigured_roles",
    "test_successful_sync_defers_maintenance_when_work_budget_is_exhausted",
    "test_successful_sync_runs_sidecar_maintenance",
    "test_unhinted_role_backstops_then_skips_within_interval",
]
