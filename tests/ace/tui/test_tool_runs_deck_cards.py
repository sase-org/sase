"""Tests for the tools-deck-cards phase (epic sase-1bt, sase-1bt.6).

Split facade: the tests now live in ``test_tool_runs_deck_cards_nav``,
``test_tool_runs_deck_cards_document``, and
``test_tool_runs_deck_cards_availability``.
This module re-exports the public names so the original import path keeps
working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_tool_runs_deck_cards_availability import (
    setup_function,
    teardown_function,
    test_fast_path_still_loads_when_details_missing_across_generation_bump,
    test_pending_selection_applies_after_document_loads,
    test_pending_selection_dropped_on_node_change,
    test_probe_opens_for_monitor_owned_runs,
    test_probe_pinned_attempt_has_no_runs,
    test_probe_reads_cached_history_without_io,
    test_probe_remote_and_clan_have_no_runs,
    test_probe_unknown_history_is_none_before_first_load,
    test_single_run_document_counts_as_success,
)
from tests.ace.tui.test_tool_runs_deck_cards_document import (
    test_block_meta_rail_facts,
    test_detail_levels_are_independent_per_card,
    test_empty_document_without_subject_or_runs,
    test_outcome_line_duration_and_settle_time,
    test_outcome_line_words,
    test_runs_detail_level_defaults_standard,
    test_search_finds_block_text,
    test_single_run_is_block_less_with_no_rail,
    test_truncated_card_says_so,
    test_two_runs_navigate_blocks,
)
from tests.ace.tui.test_tool_runs_deck_cards_nav import (
    test_both_cards_tab_order_runs_first,
    test_card_ids_runs_first,
    test_ctrl_j_k_round_trip,
    test_default_card_llm_calls_when_no_runs,
    test_default_card_runs_first_without_preference,
    test_default_card_sticky_wins,
    test_every_deck_id_has_a_document_arm,
    test_no_runs_node_keeps_single_llm_calls_tab,
    test_picker_label_counts,
    test_runs_only_node_shows_runs_only,
    test_switcher_segment_never_contains_separator,
    test_tools_has_no_view_policy,
    test_tools_is_a_card_document_deck,
)

__test__ = False

__all__ = [
    "setup_function",
    "teardown_function",
    "test_block_meta_rail_facts",
    "test_both_cards_tab_order_runs_first",
    "test_card_ids_runs_first",
    "test_ctrl_j_k_round_trip",
    "test_default_card_llm_calls_when_no_runs",
    "test_default_card_runs_first_without_preference",
    "test_default_card_sticky_wins",
    "test_detail_levels_are_independent_per_card",
    "test_empty_document_without_subject_or_runs",
    "test_every_deck_id_has_a_document_arm",
    "test_fast_path_still_loads_when_details_missing_across_generation_bump",
    "test_no_runs_node_keeps_single_llm_calls_tab",
    "test_outcome_line_duration_and_settle_time",
    "test_outcome_line_words",
    "test_pending_selection_applies_after_document_loads",
    "test_pending_selection_dropped_on_node_change",
    "test_picker_label_counts",
    "test_probe_opens_for_monitor_owned_runs",
    "test_probe_pinned_attempt_has_no_runs",
    "test_probe_reads_cached_history_without_io",
    "test_probe_remote_and_clan_have_no_runs",
    "test_probe_unknown_history_is_none_before_first_load",
    "test_runs_detail_level_defaults_standard",
    "test_runs_only_node_shows_runs_only",
    "test_search_finds_block_text",
    "test_single_run_document_counts_as_success",
    "test_single_run_is_block_less_with_no_rail",
    "test_switcher_segment_never_contains_separator",
    "test_tools_has_no_view_policy",
    "test_tools_is_a_card_document_deck",
    "test_truncated_card_says_so",
    "test_two_runs_navigate_blocks",
]
