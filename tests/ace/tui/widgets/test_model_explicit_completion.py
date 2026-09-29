"""Tests for ``==model`` prompt model completion.

Split facade: the tests now live in
``test_model_explicit_completion_interactions``,
``test_model_explicit_completion_edits``, and
``test_model_explicit_completion_catalog`` (shared helpers in
``_model_explicit_completion_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets._model_explicit_completion_shared import (
    ColdModelExplicitCompletionTestApp,
    ModelExplicitCompletionTestApp,
)
from tests.ace.tui.widgets.test_model_explicit_completion_catalog import (
    test_loading_model_rows_are_not_selectable,
    test_model_catalog_failure_can_retry_explicit_unavailable_row,
    test_model_catalog_worker_refreshes_only_matching_shortcut_kind,
    test_model_catalog_worker_rejects_stale_explicit_prompt_state,
)
from tests.ace.tui.widgets.test_model_explicit_completion_edits import (
    test_double_equals_accept_moves_value_to_existing_directive,
    test_double_equals_accept_removes_adjacent_directive_and_undo_restores,
    test_double_equals_context_and_filtering_use_model_rows_only,
    test_double_equals_context_rejects_protected_regions,
    test_double_equals_edit_plan_applies_segment_replacement,
    test_double_equals_edit_plan_spacer_cases,
    test_legacy_double_star_stays_literal_and_can_submit,
    test_unknown_double_equals_stays_literal_and_can_submit,
)
from tests.ace.tui.widgets.test_model_explicit_completion_interactions import (
    test_double_equals_accept_preserves_context_and_undo_redo,
    test_double_equals_accept_replaces_whole_token_from_mid_token_cursor,
    test_double_equals_auto_opens_and_ctrl_e_expands_without_submit,
    test_double_equals_ctrl_l_accepts_selection_without_submit_or_newline,
    test_double_equals_ctrl_t_opens_when_auto_directive_menu_disabled,
    test_double_equals_enter_submits_unexpanded_text_while_menu_is_open,
    test_double_equals_navigation_preserves_selection_while_filtering,
    test_double_equals_third_equals_and_space_dismiss_completion,
    test_equals_shortcut_switches_between_alias_and_model_in_manual_session,
    test_second_equals_takes_over_when_alias_catalog_is_loading,
    test_second_equals_takes_over_when_alias_rows_are_empty,
    test_warm_double_equals_typing_never_builds_catalog_on_key_path,
)

__test__ = False

__all__ = [
    "ColdModelExplicitCompletionTestApp",
    "ModelExplicitCompletionTestApp",
    "test_double_equals_accept_moves_value_to_existing_directive",
    "test_double_equals_accept_preserves_context_and_undo_redo",
    "test_double_equals_accept_removes_adjacent_directive_and_undo_restores",
    "test_double_equals_accept_replaces_whole_token_from_mid_token_cursor",
    "test_double_equals_auto_opens_and_ctrl_e_expands_without_submit",
    "test_double_equals_context_and_filtering_use_model_rows_only",
    "test_double_equals_context_rejects_protected_regions",
    "test_double_equals_ctrl_l_accepts_selection_without_submit_or_newline",
    "test_double_equals_ctrl_t_opens_when_auto_directive_menu_disabled",
    "test_double_equals_edit_plan_applies_segment_replacement",
    "test_double_equals_edit_plan_spacer_cases",
    "test_double_equals_enter_submits_unexpanded_text_while_menu_is_open",
    "test_double_equals_navigation_preserves_selection_while_filtering",
    "test_double_equals_third_equals_and_space_dismiss_completion",
    "test_equals_shortcut_switches_between_alias_and_model_in_manual_session",
    "test_legacy_double_star_stays_literal_and_can_submit",
    "test_loading_model_rows_are_not_selectable",
    "test_model_catalog_failure_can_retry_explicit_unavailable_row",
    "test_model_catalog_worker_refreshes_only_matching_shortcut_kind",
    "test_model_catalog_worker_rejects_stale_explicit_prompt_state",
    "test_second_equals_takes_over_when_alias_catalog_is_loading",
    "test_second_equals_takes_over_when_alias_rows_are_empty",
    "test_unknown_double_equals_stays_literal_and_can_submit",
    "test_warm_double_equals_typing_never_builds_catalog_on_key_path",
]
