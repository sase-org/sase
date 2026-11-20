"""Tests for the app-owned launchable-MRU snapshot.

The test bodies live in private modules; these imports preserve the original
pytest collection and import path.
"""

from __future__ import annotations

import pytest

from tests.ace.tui._launchable_mru_build_tests import (
    test_snapshot_ring_matches_loader_displays,
    test_worker_fast_path_skips_unchanged_inputs,
    test_build_failure_raises_for_error_snapshot,
)
from tests.ace.tui._launchable_mru_refresh_tests import (
    test_single_flight_coalesces_to_one_follow_up,
    test_stale_generation_never_publishes,
    test_token_drift_requests_one_rebuild,
    test_tick_peeks_the_change_token_off_the_main_thread,
    test_overlapping_ticks_share_one_in_flight_peek,
    test_launch_marks_pending_synchronously,
)
from tests.ace.tui._launchable_mru_cycle_tests import (
    test_burst_pins_ring_and_next_session_sees_new_generation,
    test_cold_snapshot_leaves_text_and_requests_build,
    test_error_snapshot_behaves_like_cold,
    test_warm_cycle_performs_zero_main_thread_io,
    test_warm_cycle_ctrl_n_performs_zero_main_thread_io,
    test_snapshot_cycle_matches_loader_cycle_results,
)
from tests.ace.tui._launchable_mru_identity_tests import (
    test_cold_identity_press_coalesces_warm_while_in_flight,
    test_warm_identity_resolves_aliased_project,
    test_cold_identity_project_falls_back_to_global_namespace,
    test_bare_host_without_hook_canonicalizes_synchronously,
    test_teardown_with_warm_in_flight_leaves_no_tasks,
)


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers."""
    import sase.macro._parsing as parsing
    import sase.macro._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None


__all__ = [
    "test_snapshot_ring_matches_loader_displays",
    "test_worker_fast_path_skips_unchanged_inputs",
    "test_build_failure_raises_for_error_snapshot",
    "test_single_flight_coalesces_to_one_follow_up",
    "test_stale_generation_never_publishes",
    "test_token_drift_requests_one_rebuild",
    "test_tick_peeks_the_change_token_off_the_main_thread",
    "test_overlapping_ticks_share_one_in_flight_peek",
    "test_launch_marks_pending_synchronously",
    "test_burst_pins_ring_and_next_session_sees_new_generation",
    "test_cold_snapshot_leaves_text_and_requests_build",
    "test_error_snapshot_behaves_like_cold",
    "test_warm_cycle_performs_zero_main_thread_io",
    "test_warm_cycle_ctrl_n_performs_zero_main_thread_io",
    "test_snapshot_cycle_matches_loader_cycle_results",
    "test_cold_identity_press_coalesces_warm_while_in_flight",
    "test_warm_identity_resolves_aliased_project",
    "test_cold_identity_project_falls_back_to_global_namespace",
    "test_bare_host_without_hook_canonicalizes_synchronously",
    "test_teardown_with_warm_in_flight_leaves_no_tasks",
]
