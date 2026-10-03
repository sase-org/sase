"""Facade preserving the historic ``tests.pager.test_app_three_panes`` import path.

The three-pane tests now live in :mod:`test_app_three_panes_nest`,
:mod:`test_app_three_panes_close`, and :mod:`test_app_three_panes_armed`;
this module re-exports their public test functions so existing import paths
keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_app_three_panes_armed import (
    test_armed_landing_cancels_when_target_closed,
    test_armed_unresolvable_label_clears_preview_and_capture,
    test_armed_url_label_clears_preview_and_capture,
    test_ctrl_w_arms_mru_target_with_preview_and_footer,
    test_ctrl_w_label_lands_in_captured_pane_with_own_history,
    test_escape_clears_armed_preview,
    test_structure_change_cancels_arm_and_next_label_follows_in_place,
    test_two_pane_vanished_target_cancels_instead_of_splitting,
)
from .test_app_three_panes_close import (
    test_close_last_of_three_keeps_mounted_scrolling_survivor,
    test_close_main_pane_leaves_the_pair,
    test_close_pair_pane_keeps_outer_split_and_mru_focus,
    test_escape_close_keeps_survivor_mounted,
    test_exhausted_backspace_close_keeps_survivor_mounted,
    test_third_pane_refuses_with_toast_and_keeps_state,
    test_three_pane_footer_shows_focus_both,
    test_three_pane_turn_refuses_when_transpose_does_not_fit,
)
from .test_app_three_panes_nest import (
    test_ctrl_t_turns_three_panes_keeping_widgets,
    test_erase_with_main_focused_collapses_to_single,
    test_erase_with_pair_focused_keeps_the_pair,
    test_nest_keeps_survivor_widgets_and_focuses_new_pane,
    test_nest_reaches_all_four_t_shapes,
    test_rapid_structural_keys_leave_a_valid_mounted_layout,
    test_split_keys_turn_three_panes_both_ways,
    test_swap_and_turn_keep_identity_and_reading_position,
    test_swap_in_three_panes_keeps_identity_then_click_focuses,
)

__all__ = [
    "test_armed_landing_cancels_when_target_closed",
    "test_armed_unresolvable_label_clears_preview_and_capture",
    "test_armed_url_label_clears_preview_and_capture",
    "test_close_last_of_three_keeps_mounted_scrolling_survivor",
    "test_close_main_pane_leaves_the_pair",
    "test_close_pair_pane_keeps_outer_split_and_mru_focus",
    "test_ctrl_t_turns_three_panes_keeping_widgets",
    "test_ctrl_w_arms_mru_target_with_preview_and_footer",
    "test_ctrl_w_label_lands_in_captured_pane_with_own_history",
    "test_erase_with_main_focused_collapses_to_single",
    "test_erase_with_pair_focused_keeps_the_pair",
    "test_escape_clears_armed_preview",
    "test_escape_close_keeps_survivor_mounted",
    "test_exhausted_backspace_close_keeps_survivor_mounted",
    "test_nest_keeps_survivor_widgets_and_focuses_new_pane",
    "test_nest_reaches_all_four_t_shapes",
    "test_rapid_structural_keys_leave_a_valid_mounted_layout",
    "test_split_keys_turn_three_panes_both_ways",
    "test_structure_change_cancels_arm_and_next_label_follows_in_place",
    "test_swap_and_turn_keep_identity_and_reading_position",
    "test_swap_in_three_panes_keeps_identity_then_click_focuses",
    "test_third_pane_refuses_with_toast_and_keeps_state",
    "test_three_pane_footer_shows_focus_both",
    "test_three_pane_turn_refuses_when_transpose_does_not_fit",
    "test_two_pane_vanished_target_cancels_instead_of_splitting",
]
