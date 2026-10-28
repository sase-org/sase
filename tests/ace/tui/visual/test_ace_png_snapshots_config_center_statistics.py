"""ACE PNG visual snapshots for the Admin Center Statistics tab.

This module is a facade: the tests live in the ``*_overview``, ``*_macros``,
``*_projects``, and ``*_footprint`` modules with shared helpers in
``_ace_config_center_statistics_png_snapshot_shared``. The public names are
re-exported here so the original import path keeps working.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual.test_ace_png_snapshots_config_center_statistics_footprint import (
    test_config_center_statistics_footprint_all_unknown_png_snapshot,
    test_config_center_statistics_footprint_area_narrow_png_snapshot,
    test_config_center_statistics_footprint_cold_card_png_snapshot,
    test_config_center_statistics_footprint_empty_png_snapshot,
    test_config_center_statistics_footprint_finder_png_snapshot,
    test_config_center_statistics_footprint_map_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_config_center_statistics_macros import (
    test_config_center_statistics_macros_focus_png_snapshot,
    test_config_center_statistics_macros_model_png_snapshot,
    test_config_center_statistics_macros_narrow_png_snapshot,
    test_config_center_statistics_macros_png_snapshot,
    test_config_center_statistics_perf_degraded_png_snapshot,
    test_config_center_statistics_perf_narrow_png_snapshot,
    test_config_center_statistics_perf_png_snapshot,
    test_config_center_statistics_runners_narrow_png_snapshot,
    test_config_center_statistics_runners_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_config_center_statistics_overview import (
    test_config_center_statistics_activity_png_snapshot,
    test_config_center_statistics_empty_png_snapshot,
    test_config_center_statistics_help_png_snapshot,
    test_config_center_statistics_loading_png_snapshot,
    test_config_center_statistics_narrow_png_snapshot,
    test_config_center_statistics_overview_png_snapshot,
    test_config_center_statistics_plans_questions_png_snapshot,
    test_config_center_statistics_providers_png_snapshot,
)
from tests.ace.tui.visual.test_ace_png_snapshots_config_center_statistics_projects import (
    test_config_center_statistics_projects_measuring_code_png_snapshot,
    test_config_center_statistics_projects_model_png_snapshot,
    test_config_center_statistics_projects_narrow_png_snapshot,
    test_config_center_statistics_projects_patch_png_snapshot,
    test_config_center_statistics_projects_png_snapshot,
    test_config_center_statistics_projects_repo_png_snapshot,
    test_config_center_statistics_projects_single_png_snapshot,
)

pytestmark = pytest.mark.visual

__test__ = False

__all__ = [
    "test_config_center_statistics_activity_png_snapshot",
    "test_config_center_statistics_empty_png_snapshot",
    "test_config_center_statistics_footprint_all_unknown_png_snapshot",
    "test_config_center_statistics_footprint_area_narrow_png_snapshot",
    "test_config_center_statistics_footprint_cold_card_png_snapshot",
    "test_config_center_statistics_footprint_empty_png_snapshot",
    "test_config_center_statistics_footprint_finder_png_snapshot",
    "test_config_center_statistics_footprint_map_png_snapshot",
    "test_config_center_statistics_help_png_snapshot",
    "test_config_center_statistics_loading_png_snapshot",
    "test_config_center_statistics_macros_focus_png_snapshot",
    "test_config_center_statistics_macros_model_png_snapshot",
    "test_config_center_statistics_macros_narrow_png_snapshot",
    "test_config_center_statistics_macros_png_snapshot",
    "test_config_center_statistics_narrow_png_snapshot",
    "test_config_center_statistics_overview_png_snapshot",
    "test_config_center_statistics_perf_degraded_png_snapshot",
    "test_config_center_statistics_perf_narrow_png_snapshot",
    "test_config_center_statistics_perf_png_snapshot",
    "test_config_center_statistics_plans_questions_png_snapshot",
    "test_config_center_statistics_projects_measuring_code_png_snapshot",
    "test_config_center_statistics_projects_model_png_snapshot",
    "test_config_center_statistics_projects_narrow_png_snapshot",
    "test_config_center_statistics_projects_patch_png_snapshot",
    "test_config_center_statistics_projects_png_snapshot",
    "test_config_center_statistics_projects_repo_png_snapshot",
    "test_config_center_statistics_projects_single_png_snapshot",
    "test_config_center_statistics_providers_png_snapshot",
    "test_config_center_statistics_runners_narrow_png_snapshot",
    "test_config_center_statistics_runners_png_snapshot",
]
