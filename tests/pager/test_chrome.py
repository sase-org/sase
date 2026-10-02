"""Facade preserving the historic ``tests.pager.test_chrome`` import path.

The chrome tests now live in :mod:`test_chrome_subject`,
:mod:`test_chrome_footer`, and :mod:`test_chrome_history`; this module
re-exports their public test functions so existing import paths keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_chrome_footer import (
    test_footer_legend_hides_entity_nav_for_a_single_section_document,
    test_footer_legend_names_other_pane_arm,
    test_footer_legend_names_trail_sheet_when_history_exists,
    test_footer_legend_promotes_pending_prefix_over_follow_hint,
    test_footer_legend_shows_entity_nav_for_a_multi_section_document,
    test_footer_legend_shows_follow_only_when_labels_exist,
    test_footer_shows_a_single_edit_verb,
    test_goto_command_line_idle_shows_range_and_gold_sigil,
    test_goto_command_line_invalid_restyles_digits_and_range,
    test_goto_command_line_multi_section_shows_glyph_and_title,
    test_goto_command_line_truncates_title_before_dropping_the_range,
    test_goto_command_line_typing_keeps_digits_white,
)
from .test_chrome_history import (
    test_diff_context_keeps_the_delta_segment_longest,
    test_footer_names_step_destinations_in_every_state,
    test_pill_sheds_through_fixed_forms_and_is_never_cropped,
    test_pill_text_and_styles_for_every_kind,
    test_subject_line_sheds_hint_then_count_then_context_then_pill,
)
from .test_chrome_subject import (
    test_format_char_count_scales_with_magnitude,
    test_section_icon_and_accent_fall_back_for_unknown_kinds,
    test_section_icon_and_accent_use_the_artifacts_tables,
    test_section_rule_mutes_an_intact_ws_root_token,
    test_section_rule_renders_the_agent_kind,
    test_section_rule_shape_matches_the_design_doc,
    test_subject_line_drops_the_syntax_hint_before_the_subject_at_narrow_width,
    test_subject_line_mutes_an_intact_ws_root_token,
    test_subject_line_mutes_the_current_sections_ws_token_when_multi,
    test_subject_line_omits_position_for_a_single_section_document,
    test_subject_line_omits_the_syntax_hint_when_absent,
    test_subject_line_pads_to_the_requested_width_when_it_fits,
    test_subject_line_shows_position_and_current_section_title_when_multi,
    test_subject_line_shows_the_syntax_hint_when_it_fits,
    test_subject_line_uses_the_agent_glyph_and_accent,
)

__all__ = [
    "test_diff_context_keeps_the_delta_segment_longest",
    "test_footer_legend_hides_entity_nav_for_a_single_section_document",
    "test_footer_legend_names_other_pane_arm",
    "test_footer_legend_names_trail_sheet_when_history_exists",
    "test_footer_legend_promotes_pending_prefix_over_follow_hint",
    "test_footer_legend_shows_entity_nav_for_a_multi_section_document",
    "test_footer_legend_shows_follow_only_when_labels_exist",
    "test_footer_names_step_destinations_in_every_state",
    "test_footer_shows_a_single_edit_verb",
    "test_format_char_count_scales_with_magnitude",
    "test_goto_command_line_idle_shows_range_and_gold_sigil",
    "test_goto_command_line_invalid_restyles_digits_and_range",
    "test_goto_command_line_multi_section_shows_glyph_and_title",
    "test_goto_command_line_truncates_title_before_dropping_the_range",
    "test_goto_command_line_typing_keeps_digits_white",
    "test_pill_sheds_through_fixed_forms_and_is_never_cropped",
    "test_pill_text_and_styles_for_every_kind",
    "test_section_icon_and_accent_fall_back_for_unknown_kinds",
    "test_section_icon_and_accent_use_the_artifacts_tables",
    "test_section_rule_mutes_an_intact_ws_root_token",
    "test_section_rule_renders_the_agent_kind",
    "test_section_rule_shape_matches_the_design_doc",
    "test_subject_line_drops_the_syntax_hint_before_the_subject_at_narrow_width",
    "test_subject_line_mutes_an_intact_ws_root_token",
    "test_subject_line_mutes_the_current_sections_ws_token_when_multi",
    "test_subject_line_omits_position_for_a_single_section_document",
    "test_subject_line_omits_the_syntax_hint_when_absent",
    "test_subject_line_pads_to_the_requested_width_when_it_fits",
    "test_subject_line_shows_position_and_current_section_title_when_multi",
    "test_subject_line_shows_the_syntax_hint_when_it_fits",
    "test_subject_line_uses_the_agent_glyph_and_accent",
    "test_subject_line_sheds_hint_then_count_then_context_then_pill",
]
