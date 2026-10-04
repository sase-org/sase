"""Behavior of the mini-macro target name panel.

Facade preserving the historic
``tests.ace.tui.modals.test_mini_macro_name_modal`` import path. The
suites now live in the sibling ``test_mini_macro_name_modal_*``
modules (shared fixtures in ``_mini_macro_name_modal_helpers``); this
module re-exports every public test so existing import paths keep working.
Only public names cross the module boundary here.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from tests.ace.tui.modals.test_mini_macro_name_modal_actions import (
    test_exact_editable_match_returns_edit_action,
    test_incompatible_exact_match_refuses_open,
    test_invalid_name_enter_is_inert,
    test_locked_incompatible_destination_refuses_open,
    test_new_name_returns_create_target,
    test_read_only_match_returns_override_action,
)
from tests.ace.tui.modals.test_mini_macro_name_modal_navigation import (
    test_ctrl_n_moves_matches_without_changing_destination,
    test_name_step_shows_stepper_saving_to_and_hints,
    test_prefix_order_tab_completion_and_match_navigation_keep_input_focus,
    test_shift_tab_returns_change_location_request,
    test_stale_async_analysis_is_not_cached,
    test_tab_completion_keeps_locked_destination,
)
from tests.ace.tui.modals.test_mini_macro_name_modal_verdicts import (
    test_build_verdict_describes_shadowed_create,
    test_default_config_loader_id_uses_override_warning,
    test_fork_verdict_suggests_shift_tab_to_other_destination,
    test_fork_warning_when_destination_wins_counts_other_definitions,
    test_read_only_override_warning_uses_active_outside_rows_copy,
    test_shadowed_destination_edit_is_a_warning_and_keeps_edit_action,
)

__all__ = [
    "test_invalid_name_enter_is_inert",
    "test_new_name_returns_create_target",
    "test_exact_editable_match_returns_edit_action",
    "test_read_only_match_returns_override_action",
    "test_incompatible_exact_match_refuses_open",
    "test_locked_incompatible_destination_refuses_open",
    "test_prefix_order_tab_completion_and_match_navigation_keep_input_focus",
    "test_ctrl_n_moves_matches_without_changing_destination",
    "test_stale_async_analysis_is_not_cached",
    "test_shift_tab_returns_change_location_request",
    "test_tab_completion_keeps_locked_destination",
    "test_name_step_shows_stepper_saving_to_and_hints",
    "test_fork_verdict_suggests_shift_tab_to_other_destination",
    "test_build_verdict_describes_shadowed_create",
    "test_shadowed_destination_edit_is_a_warning_and_keeps_edit_action",
    "test_fork_warning_when_destination_wins_counts_other_definitions",
    "test_read_only_override_warning_uses_active_outside_rows_copy",
    "test_default_config_loader_id_uses_override_warning",
]
