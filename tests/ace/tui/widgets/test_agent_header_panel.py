"""Mounted header-panel behavior for the Agents tab sticky identity header.

Split facade: the tests now live in ``test_agent_header_panel_basic``,
``test_agent_header_panel_preview``, and ``test_agent_header_panel_scroll``
(shared helpers in ``_agent_header_panel_shared``). This module re-exports
the public names so the original import path keeps working. It collects no
tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_agent_header_panel_basic import (
    test_body_excludes_identity_lines,
    test_bottom_pinned_body_stays_pinned_across_toggle,
    test_clan_selection_shows_header,
    test_empty_state_hides_header,
    test_expanded_state_persists_across_selection_and_tribe,
    test_header_collapsed_by_default_with_title_and_hint,
    test_hint_document_forces_expansion,
    test_search_overlay_keeps_header_visible,
    test_secondary_only_keeps_header_visible_and_toggleable,
    test_toggle_expands_to_full_fields_and_back,
    test_toggle_unavailable_while_prompt_input_owns_keys,
)
from tests.ace.tui.widgets.test_agent_header_panel_preview import (
    test_bottom_pinned_body_stays_pinned_across_row_count_change,
    test_card_rows_are_padded_and_repaint_on_width_change,
    test_collapsed_content_rows_are_exact,
    test_collapsed_preview_shows_quote_bar_and_body_omits_xprompt,
    test_column_resize_changes_budget,
    test_exact_fit_shows_no_ellipsis_or_count,
    test_expand_shows_full_xprompt_and_toggles_back,
    test_hidden_line_subtitle_uses_singular_for_one_line,
    test_no_phantom_row_rule_in_stylesheet,
    test_overflow_subtitle_names_hidden_lines,
    test_pending_hold_keeps_rows_then_settles,
    test_preview_row_count_matches_budget_and_short_prompt_fits,
    test_row_cap_setting_changes_collapsed_rows,
    test_share_zero_hides_preview_but_expanded_keeps_xprompt,
    test_visited_agent_cheap_path_shows_preview,
)
from tests.ace.tui.widgets.test_agent_header_panel_scroll import (
    test_expanded_overflowing_header_claims_half_page_scroll,
    test_header_boundary_claims_key_without_moving_deck,
    test_header_fallback_targets_focused_deck,
    test_hint_expanded_header_claims_scroll,
    test_non_main_focused_deck_header_still_claims,
    test_short_viewport_header_step_is_at_least_one_row,
)

__test__ = False

__all__ = [
    "test_body_excludes_identity_lines",
    "test_bottom_pinned_body_stays_pinned_across_row_count_change",
    "test_bottom_pinned_body_stays_pinned_across_toggle",
    "test_card_rows_are_padded_and_repaint_on_width_change",
    "test_clan_selection_shows_header",
    "test_collapsed_content_rows_are_exact",
    "test_collapsed_preview_shows_quote_bar_and_body_omits_xprompt",
    "test_column_resize_changes_budget",
    "test_empty_state_hides_header",
    "test_exact_fit_shows_no_ellipsis_or_count",
    "test_expand_shows_full_xprompt_and_toggles_back",
    "test_expanded_overflowing_header_claims_half_page_scroll",
    "test_expanded_state_persists_across_selection_and_tribe",
    "test_header_boundary_claims_key_without_moving_deck",
    "test_header_collapsed_by_default_with_title_and_hint",
    "test_header_fallback_targets_focused_deck",
    "test_hidden_line_subtitle_uses_singular_for_one_line",
    "test_hint_document_forces_expansion",
    "test_hint_expanded_header_claims_scroll",
    "test_no_phantom_row_rule_in_stylesheet",
    "test_non_main_focused_deck_header_still_claims",
    "test_overflow_subtitle_names_hidden_lines",
    "test_pending_hold_keeps_rows_then_settles",
    "test_preview_row_count_matches_budget_and_short_prompt_fits",
    "test_row_cap_setting_changes_collapsed_rows",
    "test_search_overlay_keeps_header_visible",
    "test_secondary_only_keeps_header_visible_and_toggleable",
    "test_share_zero_hides_preview_but_expanded_keeps_xprompt",
    "test_short_viewport_header_step_is_at_least_one_row",
    "test_toggle_expands_to_full_fields_and_back",
    "test_toggle_unavailable_while_prompt_input_owns_keys",
    "test_visited_agent_cheap_path_shows_preview",
]
