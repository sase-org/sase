"""Public import facade for new-project source-stage tests.

The cases live in private modules so they stay out of pytest's direct file
discovery; this module keeps the original import path and collection behavior.
"""

from __future__ import annotations

from tests.ace.tui.modals._new_project_source_flows import (
    test_bracketed_paste_focuses_filter,
    test_discovery_pins_create_row_and_n_opens_create,
    test_filter_and_enter_advance_the_modal_without_an_entry_point,
    test_loading_row_cannot_be_chosen,
    test_n_in_filter_stays_text,
    test_no_owners_card_shows_with_create_row,
    test_provider_selection_write_preserves_owner_prefs,
    test_tab_selection_persists_last_provider_off_thread,
)
from tests.ace.tui.modals._new_project_source_lifecycle import (
    test_disabled_tab_fallback_does_not_persist_provider,
    test_post_remedy_refresh_queues_behind_load,
    test_tool_missing_disables_provider_tab,
    test_unmount_cancels_owner_refresh_jobs,
)
from tests.ace.tui.modals._new_project_source_remedy import (
    test_filter_typing_and_highlight_spawn_no_subprocess,
    test_highlight_paints_before_debounced_probe_runs,
    test_remedy_falls_back_to_provider_level,
    test_remedy_suspend_failure_notifies,
    test_remedy_suspend_unsupported_notifies,
)
from tests.ace.tui.modals._new_project_source_view import (
    test_cache_age_comes_from_inputs_timestamp,
    test_collapsed_detail_covers_every_card_kind,
    test_create_row_pins_first_across_filter_and_states,
    test_detail_status_wording,
    test_health_chip_sanitizes_account_and_drops_cached_when_live,
    test_health_chip_states,
    test_hidden_enabled_project_row_names_show_action,
    test_loading_rows_are_unselectable_placeholders,
    test_no_owners_detail_points_at_config,
    test_ref_less_disabled_rows_promise_no_action,
    test_source_groups_hidden_counts_and_hidden_filter,
    test_source_hint_line_keeps_choose_and_remedy,
    test_source_paste_ref_becomes_a_synthetic_row,
    test_truncation_footer_names_filter_and_paste,
)

__all__ = (
    "test_bracketed_paste_focuses_filter",
    "test_cache_age_comes_from_inputs_timestamp",
    "test_collapsed_detail_covers_every_card_kind",
    "test_create_row_pins_first_across_filter_and_states",
    "test_detail_status_wording",
    "test_disabled_tab_fallback_does_not_persist_provider",
    "test_discovery_pins_create_row_and_n_opens_create",
    "test_filter_and_enter_advance_the_modal_without_an_entry_point",
    "test_filter_typing_and_highlight_spawn_no_subprocess",
    "test_health_chip_sanitizes_account_and_drops_cached_when_live",
    "test_health_chip_states",
    "test_hidden_enabled_project_row_names_show_action",
    "test_highlight_paints_before_debounced_probe_runs",
    "test_loading_row_cannot_be_chosen",
    "test_loading_rows_are_unselectable_placeholders",
    "test_n_in_filter_stays_text",
    "test_no_owners_card_shows_with_create_row",
    "test_no_owners_detail_points_at_config",
    "test_post_remedy_refresh_queues_behind_load",
    "test_provider_selection_write_preserves_owner_prefs",
    "test_ref_less_disabled_rows_promise_no_action",
    "test_remedy_falls_back_to_provider_level",
    "test_remedy_suspend_failure_notifies",
    "test_remedy_suspend_unsupported_notifies",
    "test_source_groups_hidden_counts_and_hidden_filter",
    "test_source_hint_line_keeps_choose_and_remedy",
    "test_source_paste_ref_becomes_a_synthetic_row",
    "test_tab_selection_persists_last_provider_off_thread",
    "test_tool_missing_disables_provider_tab",
    "test_truncation_footer_names_filter_and_paste",
    "test_unmount_cancels_owner_refresh_jobs",
)
