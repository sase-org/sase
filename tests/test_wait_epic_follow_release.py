"""Release-phase regressions: every release path shares one decision.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests._wait_epic_follow_release_helpers import NOW
from tests.test_wait_epic_follow_release_decision import (
    test_attributed_epic_heals_missing_record,
    test_closed_epic_promotes_first_then_releases,
    test_foreign_epic_id_appends_verbatim,
    test_implicit_targets_stay_unarmed,
    test_marker_without_armed_field_releases_as_today,
    test_monitor_path_launching_then_following,
    test_non_list_armed_field_means_no_armed_targets,
    test_phase_worker_child_epic_is_followed,
    test_phase_worker_inherited_epic_is_not_followed,
    test_pinned_following_pin_is_not_repromoted,
    test_plain_tale_end_is_none_and_releasable,
    test_plan_in_review_stays_agent,
    test_plan_rejected_stays_parked,
    test_proc_fallback_launching_does_not_release,
    test_recorded_epic_promotes_and_parks_first_pass,
    test_several_recorded_epics_append_in_reducer_order,
    test_skip_mode_blocks_launch_skipped,
    test_stale_reservation_blocks_with_resume_command,
    test_stale_view_withholds_promotion,
    test_unresolved_unarmed_waiter_stays_parked,
    test_waiter_own_epic_is_guarded,
)
from tests.test_wait_epic_follow_release_paths import (
    test_apply_patch_compare_and_set_abort_leaves_file_unchanged,
    test_apply_patch_persists_follows_beads_and_deps,
    test_dismiss_launching_target_blocks_without_memoize,
    test_release_paths_agree_on_promotion_snapshot,
    test_release_paths_agree_on_unarmed_snapshot,
    test_run_now_writes_unwait_ready_without_release_decision,
    test_set_waiting_until_missing_marker_is_noop,
    test_set_waiting_until_preserves_follows_and_derived_beads,
    test_wait_epic_follows_wire_round_trip,
)

__test__ = False

__all__ = [
    "NOW",
    "test_apply_patch_compare_and_set_abort_leaves_file_unchanged",
    "test_apply_patch_persists_follows_beads_and_deps",
    "test_attributed_epic_heals_missing_record",
    "test_closed_epic_promotes_first_then_releases",
    "test_dismiss_launching_target_blocks_without_memoize",
    "test_foreign_epic_id_appends_verbatim",
    "test_implicit_targets_stay_unarmed",
    "test_marker_without_armed_field_releases_as_today",
    "test_monitor_path_launching_then_following",
    "test_non_list_armed_field_means_no_armed_targets",
    "test_phase_worker_child_epic_is_followed",
    "test_phase_worker_inherited_epic_is_not_followed",
    "test_pinned_following_pin_is_not_repromoted",
    "test_plain_tale_end_is_none_and_releasable",
    "test_plan_in_review_stays_agent",
    "test_plan_rejected_stays_parked",
    "test_proc_fallback_launching_does_not_release",
    "test_recorded_epic_promotes_and_parks_first_pass",
    "test_release_paths_agree_on_promotion_snapshot",
    "test_release_paths_agree_on_unarmed_snapshot",
    "test_run_now_writes_unwait_ready_without_release_decision",
    "test_several_recorded_epics_append_in_reducer_order",
    "test_set_waiting_until_missing_marker_is_noop",
    "test_set_waiting_until_preserves_follows_and_derived_beads",
    "test_skip_mode_blocks_launch_skipped",
    "test_stale_reservation_blocks_with_resume_command",
    "test_stale_view_withholds_promotion",
    "test_unresolved_unarmed_waiter_stays_parked",
    "test_wait_epic_follows_wire_round_trip",
    "test_waiter_own_epic_is_guarded",
]
