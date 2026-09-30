"""Fleet refresh laziness regressions.

Split facade: the tests now live in
``test_agents_fleet_refresh_laziness_projection`` and
``test_agents_fleet_refresh_laziness_refresh``. This module re-exports the
public names so the original import path keeps working. It collects no tests
itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agents_fleet_refresh_laziness_projection import (
    test_agents_fleet_problem_text_reports_only_actionable_problems,
    test_apply_fleet_projection_forced_remote_sources_repaint,
    test_apply_fleet_projection_repaints_changed_row,
    test_apply_fleet_projection_skips_unchanged_reproject,
    test_host_freshness_only_change_patches_rows_without_reprojecting,
    test_local_roster_change_reprojects_tree,
    test_revision_bump_reprojects_tree,
    test_snapshot_identity_change_reprojects_tree,
    test_unchanged_refresh_skips_tree_projection,
)
from tests.ace.tui.test_agents_fleet_refresh_laziness_refresh import (
    test_agents_refresh_hydrates_catalog,
    test_fleet_catalog_refresh_requests_legal_pages_and_logical_keys,
    test_fleet_refresh_apply_defers_behind_active_navigation,
    test_fleet_refresh_preserves_feed_issues_with_config_diagnostics,
    test_zero_machine_config_refresh_performs_no_remote_work,
)

__test__ = False

__all__ = [
    "test_agents_fleet_problem_text_reports_only_actionable_problems",
    "test_agents_refresh_hydrates_catalog",
    "test_apply_fleet_projection_forced_remote_sources_repaint",
    "test_apply_fleet_projection_repaints_changed_row",
    "test_apply_fleet_projection_skips_unchanged_reproject",
    "test_fleet_catalog_refresh_requests_legal_pages_and_logical_keys",
    "test_fleet_refresh_apply_defers_behind_active_navigation",
    "test_fleet_refresh_preserves_feed_issues_with_config_diagnostics",
    "test_host_freshness_only_change_patches_rows_without_reprojecting",
    "test_local_roster_change_reprojects_tree",
    "test_revision_bump_reprojects_tree",
    "test_snapshot_identity_change_reprojects_tree",
    "test_unchanged_refresh_skips_tree_projection",
    "test_zero_machine_config_refresh_performs_no_remote_work",
]
