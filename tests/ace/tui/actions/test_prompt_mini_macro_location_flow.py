"""Location-first mini-macro flow through the save-location picker.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from .test_prompt_mini_macro_location_flow_existing import (
    test_existing_editable_opens_pane_with_loaded_body,
    test_existing_finder_back_remembers_query_and_cancel_refocuses,
    test_existing_finder_origin_lost_warns,
    test_existing_read_only_override_picker_to_pane,
    test_existing_row_is_present_and_disabled_when_empty,
    test_existing_shadowed_edit_carries_warning,
    test_existing_typeahead_seeds_finder_query,
)
from .test_prompt_mini_macro_location_flow_picker import (
    test_chord_shows_picker_before_loaders_finish,
    test_enter_takes_star_default,
    test_esc_in_either_step_restores_origin,
    test_fast_typeahead_seeds_namespaced_name,
    test_hotkey_pick_opens_name_step_on_project_row,
    test_origin_vanished_closes_picker_with_warning,
    test_retargeting_open_pane_defaults_to_current,
    test_shift_tab_round_trip_rebases_name,
)
from .test_prompt_mini_macro_location_flow_replace import (
    test_existing_dirty_open_pane_confirms_before_replace,
    test_existing_replaces_clean_open_pane,
    test_existing_same_target_focuses_and_notifies,
)

__test__ = False

__all__ = [
    "test_chord_shows_picker_before_loaders_finish",
    "test_enter_takes_star_default",
    "test_esc_in_either_step_restores_origin",
    "test_existing_dirty_open_pane_confirms_before_replace",
    "test_existing_editable_opens_pane_with_loaded_body",
    "test_existing_finder_back_remembers_query_and_cancel_refocuses",
    "test_existing_finder_origin_lost_warns",
    "test_existing_read_only_override_picker_to_pane",
    "test_existing_replaces_clean_open_pane",
    "test_existing_row_is_present_and_disabled_when_empty",
    "test_existing_same_target_focuses_and_notifies",
    "test_existing_shadowed_edit_carries_warning",
    "test_existing_typeahead_seeds_finder_query",
    "test_fast_typeahead_seeds_namespaced_name",
    "test_hotkey_pick_opens_name_step_on_project_row",
    "test_origin_vanished_closes_picker_with_warning",
    "test_retargeting_open_pane_defaults_to_current",
    "test_shift_tab_round_trip_rebases_name",
]
