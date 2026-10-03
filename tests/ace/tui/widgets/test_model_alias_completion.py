"""Tests for ``=alias`` prompt model completion.

Split facade: the tests now live in
``test_model_alias_completion_interactions``,
``test_model_alias_completion_edits``, and
``test_model_alias_completion_catalog`` (shared helpers in
``_model_alias_completion_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests._macro_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)
from tests.ace.tui.widgets._model_alias_completion_shared import (
    ColdModelAliasCompletionTestApp,
    ModelAliasCompletionTestApp,
)
from tests.ace.tui.widgets.test_model_alias_completion_catalog import (
    test_cold_model_alias_catalog_shows_loading_without_blocking_keys,
    test_loading_model_alias_row_is_not_selectable,
    test_model_alias_catalog_cache_miss_after_loaded_reschedules,
    test_model_alias_catalog_failure_can_retry_from_unavailable_row,
    test_model_alias_catalog_request_does_not_revive_inactive_stack_pane,
    test_model_alias_catalog_worker_refreshes_matching_request,
    test_model_alias_catalog_worker_rejects_stale_prompt_state,
)
from tests.ace.tui.widgets.test_model_alias_completion_edits import (
    test_equals_alias_accept_moves_value_to_existing_directive,
    test_equals_alias_accept_removes_adjacent_directive_and_undo_restores,
    test_equals_alias_context_detects_prompt_boundaries,
    test_equals_alias_context_rejects_protected_regions_and_unicode_columns,
    test_equals_alias_edit_plan_applies_segment_replacement,
    test_equals_alias_edit_plan_is_cursor_complete,
    test_legacy_star_alias_stays_literal_and_can_submit,
    test_unknown_equals_alias_stays_literal_and_can_submit,
)
from tests.ace.tui.widgets.test_model_alias_completion_interactions import (
    test_equals_alias_accept_preserves_context_and_undo_redo,
    test_equals_alias_accept_replaces_whole_token_from_mid_token_cursor,
    test_equals_alias_auto_opens_and_ctrl_e_expands_without_submit,
    test_equals_alias_ctrl_l_accepts_selection_without_submit_or_newline,
    test_equals_alias_ctrl_t_opens_when_auto_directive_menu_is_disabled,
    test_equals_alias_enter_submits_unexpanded_text_while_menu_is_open,
    test_equals_alias_navigation_preserves_selection_while_filtering,
    test_equals_alias_subtitle_omits_missing_description,
)

__test__ = False

__all__ = [
    "ColdModelAliasCompletionTestApp",
    "ModelAliasCompletionTestApp",
    "clear_model_completion_cache",
    "test_cold_model_alias_catalog_shows_loading_without_blocking_keys",
    "test_equals_alias_accept_moves_value_to_existing_directive",
    "test_equals_alias_accept_preserves_context_and_undo_redo",
    "test_equals_alias_accept_removes_adjacent_directive_and_undo_restores",
    "test_equals_alias_accept_replaces_whole_token_from_mid_token_cursor",
    "test_equals_alias_auto_opens_and_ctrl_e_expands_without_submit",
    "test_equals_alias_context_detects_prompt_boundaries",
    "test_equals_alias_context_rejects_protected_regions_and_unicode_columns",
    "test_equals_alias_ctrl_l_accepts_selection_without_submit_or_newline",
    "test_equals_alias_ctrl_t_opens_when_auto_directive_menu_is_disabled",
    "test_equals_alias_edit_plan_applies_segment_replacement",
    "test_equals_alias_edit_plan_is_cursor_complete",
    "test_equals_alias_enter_submits_unexpanded_text_while_menu_is_open",
    "test_equals_alias_navigation_preserves_selection_while_filtering",
    "test_equals_alias_subtitle_omits_missing_description",
    "test_legacy_star_alias_stays_literal_and_can_submit",
    "test_loading_model_alias_row_is_not_selectable",
    "test_model_alias_catalog_cache_miss_after_loaded_reschedules",
    "test_model_alias_catalog_failure_can_retry_from_unavailable_row",
    "test_model_alias_catalog_request_does_not_revive_inactive_stack_pane",
    "test_model_alias_catalog_worker_refreshes_matching_request",
    "test_model_alias_catalog_worker_rejects_stale_prompt_state",
    "test_unknown_equals_alias_stays_literal_and_can_submit",
]
