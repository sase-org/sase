"""Tests for the agent ARTIFACTS Beads prompt-panel rows (bead sase-14j.5).

Split facade: the tests now live in ``test_agent_bead_touch_rows_glyphs``,
``test_agent_bead_touch_rows_basic``, ``test_agent_bead_touch_rows_notes``,
``test_agent_bead_touch_rows_lane``, and ``test_agent_bead_touch_rows_closed``
(shared helpers in ``_agent_bead_touch_rows_shared``). This module re-exports
the public names so the original import path keeps working. It collects no
tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_agent_bead_touch_rows_basic import (
    test_assigned_only_bead_renders_without_verbs,
    test_assigned_only_bead_shows_resolved_title,
    test_created_plus_closed_keeps_closed_pill_and_created_chip,
    test_created_row_shows_pill_title_and_why,
    test_created_row_without_reason_falls_back_to_title,
    test_creation_reason_sanitizes_controls_and_bounds_lines,
    test_empty_entries_appends_nothing,
    test_read_reason_keeps_title_with_explicit_label,
    test_row_order_palette_and_title,
    test_truncated_creation_reason_links_to_bead_detail,
)
from tests.ace.tui.widgets.test_agent_bead_touch_rows_closed import (
    test_lane_header_announces_standing_close_count,
    test_lane_header_without_closes_is_unchanged,
    test_narrow_console_keeps_pill_contiguous,
    test_no_close_row_renders_exactly_as_before,
    test_non_standing_row_keeps_struck_closed_and_reopened_since,
    test_overflow_footer_uses_hidden_earliest_and_hidden_closed,
    test_standing_canceled_row_shows_grey_pill_and_resolution,
    test_standing_close_keeps_labeled_title_close_and_read,
    test_standing_close_without_reason_falls_back_to_title,
    test_standing_done_row_shows_pill_and_drops_closed_chip,
    test_visible_selection_keeps_older_standing_close_and_hints,
)
from tests.ace.tui.widgets.test_agent_bead_touch_rows_glyphs import (
    test_bead_glyphs_are_single_cell,
    test_created_row_reports_no_assignment_chip,
    test_glyph_precedence_closed_over_created_over_edited_over_read,
    test_single_counts_carry_no_suffix,
    test_verb_chip_order_assigned_then_durable_then_read_then_viewed,
)
from tests.ace.tui.widgets.test_agent_bead_touch_rows_lane import (
    test_bead_id_never_truncates_at_narrow_widths,
    test_bead_read_migrates_out_of_reads,
    test_beads_lead_reads_in_lane_and_header,
    test_cheap_header_renders_beads_without_index_read,
    test_clan_hint_target_rejects_invalid_bead_id,
    test_clan_hint_target_returns_bead_ref,
    test_empty_beads_renders_no_subsection_or_count,
    test_long_title_wraps_within_cell_limit,
)
from tests.ace.tui.widgets.test_agent_bead_touch_rows_notes import (
    test_attributed_rows_render_role_labels,
    test_hints_map_bead_refs_and_skip_invalid_ids,
    test_no_reason_line_without_reason_or_title,
    test_note_preview_is_attributed_bounded_and_keeps_read_reason,
    test_note_preview_physical_body_stays_three_lines_at_card_widths,
    test_note_preview_wraps_to_passed_line_cell_limit,
    test_overflow_footer_and_cap,
    test_read_reason_yields_indent_before_words_in_narrow_cards,
    test_title_falls_back_when_no_read_reason,
)

__test__ = False

__all__ = [
    "test_assigned_only_bead_renders_without_verbs",
    "test_assigned_only_bead_shows_resolved_title",
    "test_attributed_rows_render_role_labels",
    "test_bead_glyphs_are_single_cell",
    "test_bead_id_never_truncates_at_narrow_widths",
    "test_bead_read_migrates_out_of_reads",
    "test_beads_lead_reads_in_lane_and_header",
    "test_cheap_header_renders_beads_without_index_read",
    "test_clan_hint_target_rejects_invalid_bead_id",
    "test_clan_hint_target_returns_bead_ref",
    "test_created_plus_closed_keeps_closed_pill_and_created_chip",
    "test_created_row_reports_no_assignment_chip",
    "test_created_row_shows_pill_title_and_why",
    "test_created_row_without_reason_falls_back_to_title",
    "test_creation_reason_sanitizes_controls_and_bounds_lines",
    "test_empty_beads_renders_no_subsection_or_count",
    "test_empty_entries_appends_nothing",
    "test_glyph_precedence_closed_over_created_over_edited_over_read",
    "test_hints_map_bead_refs_and_skip_invalid_ids",
    "test_lane_header_announces_standing_close_count",
    "test_lane_header_without_closes_is_unchanged",
    "test_long_title_wraps_within_cell_limit",
    "test_narrow_console_keeps_pill_contiguous",
    "test_no_close_row_renders_exactly_as_before",
    "test_no_reason_line_without_reason_or_title",
    "test_non_standing_row_keeps_struck_closed_and_reopened_since",
    "test_note_preview_is_attributed_bounded_and_keeps_read_reason",
    "test_note_preview_physical_body_stays_three_lines_at_card_widths",
    "test_note_preview_wraps_to_passed_line_cell_limit",
    "test_overflow_footer_and_cap",
    "test_overflow_footer_uses_hidden_earliest_and_hidden_closed",
    "test_read_reason_keeps_title_with_explicit_label",
    "test_read_reason_yields_indent_before_words_in_narrow_cards",
    "test_row_order_palette_and_title",
    "test_single_counts_carry_no_suffix",
    "test_standing_canceled_row_shows_grey_pill_and_resolution",
    "test_standing_close_keeps_labeled_title_close_and_read",
    "test_standing_close_without_reason_falls_back_to_title",
    "test_standing_done_row_shows_pill_and_drops_closed_chip",
    "test_title_falls_back_when_no_read_reason",
    "test_truncated_creation_reason_links_to_bead_detail",
    "test_verb_chip_order_assigned_then_durable_then_read_then_viewed",
    "test_visible_selection_keeps_older_standing_close_and_hints",
]
