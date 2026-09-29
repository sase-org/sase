"""Panel-shell tests for the ``:`` Command Line.

Split facade: the tests now live in ``test_panel_shell_basics``,
``test_panel_shell_history``, ``test_panel_shell_submit``, and
``test_panel_shell_pilot``. This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.command_line.test_panel_shell_basics import (
    test_action_pushes_command_line_screen_unconditionally,
    test_clear_transcript_keeps_running_blocks,
    test_palette_moved_tip_marker_round_trip,
    test_palette_row_always_visible_after_land,
    test_session_caps_blocks_at_200,
    test_session_defaults_for_reopen,
    test_session_for_app_is_stable,
    test_strip_implicit_prefix_keeps_other_text_verbatim,
    test_tokenize_strips_implicit_sase_prefix,
)
from tests.ace.tui.command_line.test_panel_shell_history import (
    history_file,
    test_ghost_prefers_same_cwd,
    test_history_enforces_lru_cap,
    test_history_lock_serializes_concurrent_records,
    test_prefix_walk_prefers_same_cwd,
    test_real_input_ctrl_f_accepts_only_an_active_menu,
    test_real_input_walks_history_and_never_pastes_mid_line_ghost,
    test_record_dedups_repeats_with_count,
)
from tests.ace.tui.command_line.test_panel_shell_pilot import (
    test_empty_panel_escape_follows_the_hide_panel_binding,
    test_empty_panel_semicolon_hops_to_palette_and_back,
    test_grammar_loader_notifies_every_pending_screen_callback,
    test_grammar_readiness_through_real_loader_with_in_process_grammar,
    test_grammar_ready_refreshes_open_empty_panel_without_a_keystroke,
    test_panel_escape_keeps_draft_across_reopen,
    test_real_input_history_filters_prefix_and_resets_new_walk,
    test_real_input_right_accepts_ghost_at_line_end,
    test_submit_failure_turns_block_red_and_restores_line,
    test_submit_happy_path_settles_on_exit_completion,
)
from tests.ace.tui.command_line.test_panel_shell_submit import (
    test_collapsed_body_shows_last_12_lines,
    test_context_chip_marks_pins_and_truncates,
    test_exit_elapsed_uses_one_clock_for_live_blocks,
    test_gutter_and_header_metadata,
    test_prepare_submit_rejects_blank_and_guards_double_enter,
    test_sanitize_collapses_cr_and_drops_osc_keeps_sgr,
    test_screen_submit_uses_thread_worker_not_await,
    test_submit_failure_path_restores_state,
    test_submit_success_and_exit_settle,
    test_tail_polling_never_touches_message_pump,
)

__test__ = False

__all__ = [
    "history_file",
    "test_action_pushes_command_line_screen_unconditionally",
    "test_clear_transcript_keeps_running_blocks",
    "test_collapsed_body_shows_last_12_lines",
    "test_context_chip_marks_pins_and_truncates",
    "test_empty_panel_escape_follows_the_hide_panel_binding",
    "test_empty_panel_semicolon_hops_to_palette_and_back",
    "test_exit_elapsed_uses_one_clock_for_live_blocks",
    "test_ghost_prefers_same_cwd",
    "test_grammar_loader_notifies_every_pending_screen_callback",
    "test_grammar_readiness_through_real_loader_with_in_process_grammar",
    "test_grammar_ready_refreshes_open_empty_panel_without_a_keystroke",
    "test_gutter_and_header_metadata",
    "test_history_enforces_lru_cap",
    "test_history_lock_serializes_concurrent_records",
    "test_palette_moved_tip_marker_round_trip",
    "test_palette_row_always_visible_after_land",
    "test_prefix_walk_prefers_same_cwd",
    "test_prepare_submit_rejects_blank_and_guards_double_enter",
    "test_real_input_ctrl_f_accepts_only_an_active_menu",
    "test_real_input_history_filters_prefix_and_resets_new_walk",
    "test_real_input_right_accepts_ghost_at_line_end",
    "test_real_input_walks_history_and_never_pastes_mid_line_ghost",
    "test_record_dedups_repeats_with_count",
    "test_sanitize_collapses_cr_and_drops_osc_keeps_sgr",
    "test_screen_submit_uses_thread_worker_not_await",
    "test_session_caps_blocks_at_200",
    "test_session_defaults_for_reopen",
    "test_session_for_app_is_stable",
    "test_strip_implicit_prefix_keeps_other_text_verbatim",
    "test_submit_failure_path_restores_state",
    "test_submit_failure_turns_block_red_and_restores_line",
    "test_submit_success_and_exit_settle",
    "test_submit_happy_path_settles_on_exit_completion",
    "test_tail_polling_never_touches_message_pump",
    "test_tokenize_strips_implicit_sase_prefix",
    "test_panel_escape_keeps_draft_across_reopen",
]
