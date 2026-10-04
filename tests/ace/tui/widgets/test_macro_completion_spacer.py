"""Tests for one-shot punctuation rewrites of macro completion spacers.

When a macro without required inputs completes to ``#name `` (a deliberate
trailing spacer), typing punctuation immediately afterward rewrites that spacer.
Snippet tabstop navigation also removes an owned spacer when advancing.
"""

from __future__ import annotations

from ._test_macro_completion_spacer_rewrites import (
    test_no_required_and_optional_only_input_predicates,
    test_optional_only_ctrl_t_single_candidate_then_colon,
    test_no_input_ctrl_t_single_candidate_then_comma,
    test_optional_only_ctrl_t_single_candidate_then_comma,
    test_completion_before_punctuation_records_no_spacer,
    test_completion_panel_accept_then_comma,
    test_optional_agent_spacer_colon_opens_agent_menu,
    test_optional_agent_spacer_colon_respects_disabled_auto_menu,
    test_no_input_soft_completion_then_comma,
    test_optional_only_selector_smart_insertion_then_comma,
    test_no_input_macro_colon_is_not_rewritten,
    test_intervening_keystroke_clears_pending_spacer,
    test_cursor_movement_invalidates_later_comma_rewrite,
    test_changed_reference_invalidates_later_comma_rewrite,
    test_absent_spacer_invalidates_later_comma_rewrite,
    test_required_text_completion_does_not_record_pending_spacer,
)

from ._test_macro_completion_spacer_tabstops import (
    test_tab_after_spacer_jumps_to_next_tabstop_without_the_space,
    test_shift_tab_after_spacer_retreats_without_the_space,
    test_tab_without_a_snippet_session_keeps_the_spacer,
    test_tab_at_the_last_tabstop_keeps_the_spacer,
    test_tab_does_not_expand_a_snippet_named_after_the_macro,
    test_cursor_movement_invalidates_the_tab_spacer_deletion,
    test_spacer_tab_deletion_is_one_shot,
)

from ._test_macro_completion_spacer_parentheses import (
    test_optional_multi_spacer_paren_opens_argument_menu,
    test_optional_multi_spacer_paren_accept_topic,
    test_optional_multi_spacer_paren_respects_disabled_auto_menu,
    test_no_input_spacer_paren_keeps_space,
    test_spacer_paren_preserves_prefix_and_suffix,
    test_spacer_paren_uses_literal_when_pairing_unsafe,
    test_spacer_paren_selection_and_normal_mode_keep_space,
    test_spacer_paren_is_one_undo_step,
    test_manual_lookalike_space_is_preserved_on_paren,
)

__all__ = [
    "test_no_required_and_optional_only_input_predicates",
    "test_optional_only_ctrl_t_single_candidate_then_colon",
    "test_no_input_ctrl_t_single_candidate_then_comma",
    "test_optional_only_ctrl_t_single_candidate_then_comma",
    "test_completion_before_punctuation_records_no_spacer",
    "test_completion_panel_accept_then_comma",
    "test_optional_agent_spacer_colon_opens_agent_menu",
    "test_optional_agent_spacer_colon_respects_disabled_auto_menu",
    "test_no_input_soft_completion_then_comma",
    "test_optional_only_selector_smart_insertion_then_comma",
    "test_no_input_macro_colon_is_not_rewritten",
    "test_intervening_keystroke_clears_pending_spacer",
    "test_cursor_movement_invalidates_later_comma_rewrite",
    "test_changed_reference_invalidates_later_comma_rewrite",
    "test_absent_spacer_invalidates_later_comma_rewrite",
    "test_required_text_completion_does_not_record_pending_spacer",
    "test_tab_after_spacer_jumps_to_next_tabstop_without_the_space",
    "test_shift_tab_after_spacer_retreats_without_the_space",
    "test_tab_without_a_snippet_session_keeps_the_spacer",
    "test_tab_at_the_last_tabstop_keeps_the_spacer",
    "test_tab_does_not_expand_a_snippet_named_after_the_macro",
    "test_cursor_movement_invalidates_the_tab_spacer_deletion",
    "test_spacer_tab_deletion_is_one_shot",
    "test_optional_multi_spacer_paren_opens_argument_menu",
    "test_optional_multi_spacer_paren_accept_topic",
    "test_optional_multi_spacer_paren_respects_disabled_auto_menu",
    "test_no_input_spacer_paren_keeps_space",
    "test_spacer_paren_preserves_prefix_and_suffix",
    "test_spacer_paren_uses_literal_when_pairing_unsafe",
    "test_spacer_paren_selection_and_normal_mode_keep_space",
    "test_spacer_paren_is_one_undo_step",
    "test_manual_lookalike_space_is_preserved_on_paren",
]
