"""Beautiful agent tab strip tests (sase-1bc.7).

Split facade: the tests now live in ``test_agent_tab_strip_render``,
``test_agent_tab_strip_catalog``, and ``test_agent_tab_strip_machine``.
This module re-exports the public names so the original import path keeps
working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agent_tab_strip_catalog import (
    test_arrivals_baseline_then_mark_then_clear_on_visit,
    test_badges_use_stopped_failed_unread,
    test_empty_causes_cover_all_three_states,
    test_owner_empty_state_names_query_hides,
    test_picker_modal_constructs_with_entries_only,
    test_picker_row_shows_glyph_count_and_attention,
    test_picker_search_filters_by_label,
    test_query_aware_counts_while_existence_is_not,
    test_show_empty_cause_falls_back_without_cause,
    test_show_empty_cause_falls_back_without_widget_support,
    test_show_empty_cause_feed_unavailable,
    test_show_empty_cause_genuine,
    test_show_empty_cause_query_hides,
)
from tests.ace.tui.test_agent_tab_strip_machine import (
    test_contract_version_refresh_caches_and_gates_disk,
    test_machine_health_notes_old_contract_without_feed_issues,
    test_machine_off_tab_extras_empty_without_machine_tabs,
    test_machine_off_tab_extras_names_other_tab_counts,
    test_machine_tooltip_appends_health_and_off_tab_notes,
    test_machine_tooltip_keeps_configured_description_on_named_tabs,
    test_named_accent_prefers_config_then_project_then_hash,
    test_refresh_skips_widget_update_on_unchanged_signature,
    test_repaint_signature_covers_counts_attention_health_and_arrivals,
    test_split_machine_label,
)
from tests.ace.tui.test_agent_tab_strip_render import (
    strip_plain,
    test_compact_inactive_drops_count_and_unread_but_keeps_failed,
    test_full_compact_micro_tier_plains,
    test_overflow_chip_click_opens_picker_request,
    test_overflow_chips_tint_when_hidden_tabs_need_attention,
    test_overflow_window_is_active_centered,
    test_status_sibling_reserves_cells_for_health_text,
    test_tier_for_width_picks_richest_fit,
    test_two_cell_glyph_click_ranges_are_cell_accurate,
)

__test__ = False

__all__ = [
    "strip_plain",
    "test_arrivals_baseline_then_mark_then_clear_on_visit",
    "test_badges_use_stopped_failed_unread",
    "test_compact_inactive_drops_count_and_unread_but_keeps_failed",
    "test_contract_version_refresh_caches_and_gates_disk",
    "test_empty_causes_cover_all_three_states",
    "test_full_compact_micro_tier_plains",
    "test_machine_health_notes_old_contract_without_feed_issues",
    "test_machine_off_tab_extras_empty_without_machine_tabs",
    "test_machine_off_tab_extras_names_other_tab_counts",
    "test_machine_tooltip_appends_health_and_off_tab_notes",
    "test_machine_tooltip_keeps_configured_description_on_named_tabs",
    "test_named_accent_prefers_config_then_project_then_hash",
    "test_overflow_chip_click_opens_picker_request",
    "test_overflow_chips_tint_when_hidden_tabs_need_attention",
    "test_overflow_window_is_active_centered",
    "test_owner_empty_state_names_query_hides",
    "test_picker_modal_constructs_with_entries_only",
    "test_picker_row_shows_glyph_count_and_attention",
    "test_picker_search_filters_by_label",
    "test_query_aware_counts_while_existence_is_not",
    "test_refresh_skips_widget_update_on_unchanged_signature",
    "test_repaint_signature_covers_counts_attention_health_and_arrivals",
    "test_show_empty_cause_falls_back_without_cause",
    "test_show_empty_cause_falls_back_without_widget_support",
    "test_show_empty_cause_feed_unavailable",
    "test_show_empty_cause_genuine",
    "test_show_empty_cause_query_hides",
    "test_split_machine_label",
    "test_status_sibling_reserves_cells_for_health_text",
    "test_tier_for_width_picks_richest_fit",
    "test_two_cell_glyph_click_ranges_are_cell_accurate",
]
