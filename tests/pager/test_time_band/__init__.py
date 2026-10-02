"""Pager time-band tests (phase ``time-band``).

Split from a single 926-line module into focused modules; this package
preserves the original ``tests.pager.test_time_band`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.pager.test_time_band.test_basics import (
    test_chrome_row_budget_matrix,
    test_format_age_matches_shared_renderer,
    test_glyph_and_hidden_tables_match_shared_vocabulary,
    test_honest_states_cover_every_kind,
    test_life_strip_shows_scrubber_date_owner_and_dirty,
    test_notice_modes_for_states_without_history,
    test_short_display_matches_shared_renderer,
    test_sparkline_buckets_more_versions_than_cells,
    test_sparkline_scales_logarithmically_and_marks_current,
)
from tests.pager.test_time_band.test_rows import (
    test_band_hints_lead_the_shared_sequence,
    test_folded_honest_state_reaches_the_subject_chip,
    test_instruction_cause_rows_and_chips,
    test_meaning_row_sheds_sha_agent_bead_then_sections,
    test_past_meaning_row_carries_provenance_targets,
    test_shallow_and_template_annotate_history_rows,
    test_timeline_row_markers_and_shedding,
    test_two_row_band_keeps_timeline_first_and_meaning_second,
    test_unknown_ordinal_and_empty_rows_hide,
)
from tests.pager.test_time_band.test_scrubber import (
    test_band_tint_keeps_body_text_contrast,
    test_meaning_row_shows_renamed_path,
    test_model_reads_view_diff_newer_and_subject_from_moment,
    test_scrubber_diff_ranges_adjacent_and_split,
    test_scrubber_progress_styles_for_every_kind,
    test_scrubber_slot_counts_for_every_size,
    test_timeline_row_marks_dirty_diff_against_now,
    test_timeline_row_shows_compared_range_and_endpoints,
    test_tombstone_row_replaces_meaning_row,
)

__all__ = [
    "test_band_hints_lead_the_shared_sequence",
    "test_band_tint_keeps_body_text_contrast",
    "test_chrome_row_budget_matrix",
    "test_folded_honest_state_reaches_the_subject_chip",
    "test_format_age_matches_shared_renderer",
    "test_glyph_and_hidden_tables_match_shared_vocabulary",
    "test_honest_states_cover_every_kind",
    "test_instruction_cause_rows_and_chips",
    "test_life_strip_shows_scrubber_date_owner_and_dirty",
    "test_meaning_row_sheds_sha_agent_bead_then_sections",
    "test_meaning_row_shows_renamed_path",
    "test_model_reads_view_diff_newer_and_subject_from_moment",
    "test_notice_modes_for_states_without_history",
    "test_past_meaning_row_carries_provenance_targets",
    "test_scrubber_diff_ranges_adjacent_and_split",
    "test_scrubber_progress_styles_for_every_kind",
    "test_scrubber_slot_counts_for_every_size",
    "test_shallow_and_template_annotate_history_rows",
    "test_short_display_matches_shared_renderer",
    "test_sparkline_buckets_more_versions_than_cells",
    "test_sparkline_scales_logarithmically_and_marks_current",
    "test_timeline_row_marks_dirty_diff_against_now",
    "test_timeline_row_markers_and_shedding",
    "test_timeline_row_shows_compared_range_and_endpoints",
    "test_tombstone_row_replaces_meaning_row",
    "test_two_row_band_keeps_timeline_first_and_meaning_second",
    "test_unknown_ordinal_and_empty_rows_hide",
]
