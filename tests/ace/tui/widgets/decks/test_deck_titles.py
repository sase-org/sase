"""Title, subtitle and file-line-status tests.

Split facade: the tests now live in ``test_deck_titles_title`` and
``test_deck_titles_subtitle``. This module re-exports the public names so
the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.decks.test_deck_titles_subtitle import (
    test_subtitle_drops_counts_before_slicing,
    test_subtitle_drops_switcher_before_truncating_status,
    test_subtitle_has_no_spread_tag,
    test_subtitle_slices_only_when_even_bare_labels_do_not_fit,
    test_subtitle_status_keeps_bare_switcher_before_dropping_it,
    test_subtitle_switcher_counts_only_when_known,
    test_zoom_subtitle_cards_only_unbound_keys_truncate_by_cells,
    test_zoom_subtitle_glyph_per_half,
    test_zoom_subtitle_keeps_status_while_switcher_drops,
    test_zoom_subtitle_keeps_truncated_continuation_at_width_25,
    test_zoom_subtitle_ladder_drops_counts_then_switcher_then_position,
    test_zoom_subtitle_omits_key_when_unbound,
    test_zoom_subtitle_single_has_no_position,
    test_zoom_subtitle_split_drops_position_before_truncating_counts,
    test_zoom_subtitle_truncation_preserves_styles_and_fallback_boundary,
)
from tests.ace.tui.widgets.decks.test_deck_titles_title import (
    test_chip_follows_deck_name_before_tabs,
    test_chip_ladder_prefers_long_then_short_then_tiny,
    test_chip_micro_tiny_form_keeps_text,
    test_file_line_status,
    test_files_compact_form_uses_active_label,
    test_files_crowded_tabs_skip_full_rungs_with_chip,
    test_full_tier_active_pill_and_count,
    test_locked_chip_shows_lock_and_requested_name,
    test_one_card_heading_has_no_tabs_or_chip,
    test_partial_paint_mutes_tabs_without_count,
    test_pending_and_blocked_words_sit_outside_the_chip,
    test_single_card_has_no_count,
    test_spread_counted_cue_uses_deck_noun,
    test_spread_rungs_have_no_tab_grammar,
    test_tier_falls_back_at_narrow_widths,
    test_tools_one_card_has_no_tabs_or_chip,
    test_unfocused_styling_differs,
    test_view_chip_style_is_solid_on_focus,
    test_zoomed_spread_title_still_leads_with_zoom,
    test_zoomed_title_chip_alone_below_smallest_rung,
    test_zoomed_title_chip_always_present_and_budgeted,
    test_zoomed_title_chip_style,
    test_zoomed_title_picks_rungs_against_reduced_budget,
)

__test__ = False

__all__ = [
    "test_chip_follows_deck_name_before_tabs",
    "test_chip_ladder_prefers_long_then_short_then_tiny",
    "test_chip_micro_tiny_form_keeps_text",
    "test_file_line_status",
    "test_files_compact_form_uses_active_label",
    "test_files_crowded_tabs_skip_full_rungs_with_chip",
    "test_full_tier_active_pill_and_count",
    "test_locked_chip_shows_lock_and_requested_name",
    "test_one_card_heading_has_no_tabs_or_chip",
    "test_partial_paint_mutes_tabs_without_count",
    "test_pending_and_blocked_words_sit_outside_the_chip",
    "test_single_card_has_no_count",
    "test_spread_counted_cue_uses_deck_noun",
    "test_spread_rungs_have_no_tab_grammar",
    "test_subtitle_drops_counts_before_slicing",
    "test_subtitle_drops_switcher_before_truncating_status",
    "test_subtitle_has_no_spread_tag",
    "test_subtitle_slices_only_when_even_bare_labels_do_not_fit",
    "test_subtitle_status_keeps_bare_switcher_before_dropping_it",
    "test_subtitle_switcher_counts_only_when_known",
    "test_tier_falls_back_at_narrow_widths",
    "test_tools_one_card_has_no_tabs_or_chip",
    "test_unfocused_styling_differs",
    "test_view_chip_style_is_solid_on_focus",
    "test_zoom_subtitle_cards_only_unbound_keys_truncate_by_cells",
    "test_zoom_subtitle_glyph_per_half",
    "test_zoom_subtitle_keeps_status_while_switcher_drops",
    "test_zoom_subtitle_keeps_truncated_continuation_at_width_25",
    "test_zoom_subtitle_ladder_drops_counts_then_switcher_then_position",
    "test_zoom_subtitle_omits_key_when_unbound",
    "test_zoom_subtitle_single_has_no_position",
    "test_zoom_subtitle_split_drops_position_before_truncating_counts",
    "test_zoom_subtitle_truncation_preserves_styles_and_fallback_boundary",
    "test_zoomed_spread_title_still_leads_with_zoom",
    "test_zoomed_title_chip_alone_below_smallest_rung",
    "test_zoomed_title_chip_always_present_and_budgeted",
    "test_zoomed_title_chip_style",
    "test_zoomed_title_picks_rungs_against_reduced_budget",
]
