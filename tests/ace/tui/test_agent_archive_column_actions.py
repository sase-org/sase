"""Archive column glue: paging, folds, navigation, sections, and Inbox isolation.

Drives the real controller and list model against an in-memory corpus that
follows the Rust contract (root counts in summaries, flattened ``total`` and
member rows in windows) with a fake widget and a deterministic spawn.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_column import (
    archive_container_members,
    archive_light_row,
)
from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_snapshot,
    refresh_archive_inbox_pulse,
)
from sase.ace.tui.actions.agents._core import _AgentArchiveColumnMixin
from sase.ace.tui.actions.agents._archive_view import (
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    INTENT_ACTIVATE,
    INTENT_COLLAPSE,
    INTENT_DOWN,
    INTENT_EXPAND,
    INTENT_FIRST,
    INTENT_LAST,
    INTENT_SWITCH_SECTION,
    INTENT_UP,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row

from tests.ace.tui.test_agent_archive_column_actions_list import (
    test_banner_pages_load_100_rows_and_enter_or_l_requests_the_next,
    test_cold_open_lists_open_banners_with_core_rows_and_selects_first_run,
    test_container_enter_toggles_and_workflow_children_stay_out_of_the_list,
    test_containers_expand_collapse_and_report_matching_members_only,
    test_flag_off_routes_nothing_and_paints_nothing,
    test_folding_parks_the_cursor_on_the_banner,
    test_j_k_g_G_walk_banners_and_rows_without_wrapping,
    test_keys_fall_through_to_the_inbox_when_it_owns_the_tab,
    test_l_on_an_open_banner_steps_onto_its_first_run,
    test_l_opens_a_folded_banner_h_folds_and_user_folds_stick,
    test_multi_group_banner_pages_across_its_component_days,
    test_navigation_never_touches_inbox_state,
    test_scope_token_is_stripped_before_every_corpus_call,
    test_selection_types_distinguish_banners_runs_and_the_pulse,
    test_small_complete_result_opens_every_banner,
    test_warm_reopen_needs_one_corpus_round_trip,
)

from tests.ace.tui.test_agent_archive_column_actions_interaction import (
    test_J_and_K_switch_pulse_and_list_focus_without_moving_the_inbox,
    test_click_activation_matches_the_keyboard_path,
    test_cursor_survives_a_rebuild_and_falls_to_a_neighbor_when_row_vanishes,
    test_enter_l_or_click_on_the_pulse_returns_to_the_parked_inbox,
    test_pulse_updates_live_without_rebuilding_the_list_or_resetting_detail,
    test_selected_run_in_a_folded_banner_moves_to_the_banner,
    test_widget_cursor_events_update_state_without_echoing_back,
)

from tests.ace.tui.test_agent_archive_column_actions_lifecycle import (
    test_cursor_moves_debounce_the_detail_paint_and_drop_stale_work,
    test_exact_arrival_expands_the_owning_container,
    test_exact_arrival_for_a_row_outside_the_query_gives_up_cleanly,
    test_exact_arrival_opens_the_banner_pages_to_the_run_and_selects_it,
    test_exact_arrival_pages_until_the_row_is_loaded,
    test_loading_state_paints_a_loading_row_before_the_gate_opens,
    test_rebuilding_index_lists_indexed_rows_under_a_progress_note,
    test_unavailable_index_paints_the_rebuild_hint_and_nothing_else,
    test_view_state_exposes_archive_view_constant_for_reading_callers,
)

__test__ = False

__all__ = [
    "SimpleNamespace",
    "Any",
    "archive_container_members",
    "archive_light_row",
    "archive_corpus_snapshot",
    "refresh_archive_inbox_pulse",
    "_AgentArchiveColumnMixin",
    "archive_read_only_context",
    "close_agents_archive_view",
    "get_agents_tab_selection",
    "open_agents_archive_view",
    "open_agents_archive_view_with_query",
    "route_archive_key",
    "AGENTS_VIEW_ARCHIVE",
    "INTENT_ACTIVATE",
    "INTENT_COLLAPSE",
    "INTENT_DOWN",
    "INTENT_EXPAND",
    "INTENT_FIRST",
    "INTENT_LAST",
    "INTENT_SWITCH_SECTION",
    "INTENT_UP",
    "AGENTS_VIEW_INBOX",
    "ARCHIVE_ROW_AGENT",
    "ARCHIVE_ROW_CONTAINER",
    "ARCHIVE_ROW_NONE",
    "ARCHIVE_SECTION_LIST",
    "ARCHIVE_SECTION_PULSE",
    "override_flags",
    "ColumnHarness",
    "light_row",
    "test_banner_pages_load_100_rows_and_enter_or_l_requests_the_next",
    "test_cold_open_lists_open_banners_with_core_rows_and_selects_first_run",
    "test_container_enter_toggles_and_workflow_children_stay_out_of_the_list",
    "test_containers_expand_collapse_and_report_matching_members_only",
    "test_flag_off_routes_nothing_and_paints_nothing",
    "test_folding_parks_the_cursor_on_the_banner",
    "test_j_k_g_G_walk_banners_and_rows_without_wrapping",
    "test_keys_fall_through_to_the_inbox_when_it_owns_the_tab",
    "test_l_on_an_open_banner_steps_onto_its_first_run",
    "test_l_opens_a_folded_banner_h_folds_and_user_folds_stick",
    "test_multi_group_banner_pages_across_its_component_days",
    "test_navigation_never_touches_inbox_state",
    "test_scope_token_is_stripped_before_every_corpus_call",
    "test_selection_types_distinguish_banners_runs_and_the_pulse",
    "test_small_complete_result_opens_every_banner",
    "test_warm_reopen_needs_one_corpus_round_trip",
    "test_J_and_K_switch_pulse_and_list_focus_without_moving_the_inbox",
    "test_click_activation_matches_the_keyboard_path",
    "test_cursor_survives_a_rebuild_and_falls_to_a_neighbor_when_row_vanishes",
    "test_enter_l_or_click_on_the_pulse_returns_to_the_parked_inbox",
    "test_pulse_updates_live_without_rebuilding_the_list_or_resetting_detail",
    "test_selected_run_in_a_folded_banner_moves_to_the_banner",
    "test_widget_cursor_events_update_state_without_echoing_back",
    "test_cursor_moves_debounce_the_detail_paint_and_drop_stale_work",
    "test_exact_arrival_expands_the_owning_container",
    "test_exact_arrival_for_a_row_outside_the_query_gives_up_cleanly",
    "test_exact_arrival_opens_the_banner_pages_to_the_run_and_selects_it",
    "test_exact_arrival_pages_until_the_row_is_loaded",
    "test_loading_state_paints_a_loading_row_before_the_gate_opens",
    "test_rebuilding_index_lists_indexed_rows_under_a_progress_note",
    "test_unavailable_index_paints_the_rebuild_hint_and_nothing_else",
    "test_view_state_exposes_archive_view_constant_for_reading_callers",
]
