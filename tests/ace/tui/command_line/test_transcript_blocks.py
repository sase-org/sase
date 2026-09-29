"""Transcript-block tests for the ``:`` Command Line (transcript-blocks phase).

Split facade: the tests now live in ``test_transcript_blocks_state``,
``test_transcript_blocks_toasts``, ``test_transcript_blocks_keys``, and
``test_transcript_blocks_actions`` (shared helpers in
``_transcript_blocks_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.command_line.test_transcript_blocks_actions import (
    test_K_warns_when_finished_and_confirms_when_running,
    test_p_opens_procs_with_focus_target,
    test_procs_jump_focus_selects_block_on_open,
    test_real_R_press_reruns_declined_and_notices_otherwise,
    test_real_i_a_colon_presses_return_to_insert,
    test_v_loads_an_unloaded_tail_then_opens_pager,
    test_v_opens_pager_for_selected_block,
    test_y_and_Y_copy_output_and_command,
)
from tests.ace.tui.command_line.test_transcript_blocks_keys import (
    test_block_keys_select_move_and_switch_hints,
    test_e_loads_line_into_input,
    test_forwarded_k_key_enters_transcript_selection,
    test_o_toggles_expand_and_x_removes,
    test_r_reruns_and_R_is_limited_to_declined_blocks,
    test_unselected_normal_input_keeps_vim_editing_and_redo,
)
from tests.ace.tui.command_line.test_transcript_blocks_state import (
    test_block_from_proc_maps_terminal_and_running,
    test_clear_transcript_drops_stale_selection,
    test_command_line_from_proc_prefers_argv,
    test_ensure_block_for_proc_adds_missing_block,
    test_ensure_block_for_proc_pruned,
    test_first_restored_index,
    test_load_block_tail_text_missing_log_marks_pruned,
    test_refresh_pruned_flags_keeps_cached_tail,
    test_remove_block_keeps_proc_record_and_falls_back,
    test_render_selected_unseen_divider_and_rotation,
    test_restore_missing_blocks_skips_known_procs,
    test_select_first_last_and_empty_session,
    test_select_restore_rows_enforces_limit_newest,
    test_select_restore_rows_filters_and_orders,
    test_selecting_clears_unseen_dot,
    test_selection_moves_and_enters_at_last_block,
)
from tests.ace.tui.command_line.test_transcript_blocks_toasts import (
    test_completion_toast_omits_hint_while_unbound,
    test_completion_toast_text_success_and_failure,
    test_deliver_exit_toasts_when_hidden_and_marks_unseen,
    test_is_command_line_row_checks_tag,
    test_open_command_line_on_block_reports_pruned,
    test_open_command_line_on_block_selects_existing,
    test_procs_enter_routes_command_line_rows_to_panel,
)

__test__ = False

__all__ = [
    "test_K_warns_when_finished_and_confirms_when_running",
    "test_block_from_proc_maps_terminal_and_running",
    "test_block_keys_select_move_and_switch_hints",
    "test_clear_transcript_drops_stale_selection",
    "test_command_line_from_proc_prefers_argv",
    "test_completion_toast_omits_hint_while_unbound",
    "test_completion_toast_text_success_and_failure",
    "test_deliver_exit_toasts_when_hidden_and_marks_unseen",
    "test_e_loads_line_into_input",
    "test_ensure_block_for_proc_adds_missing_block",
    "test_ensure_block_for_proc_pruned",
    "test_first_restored_index",
    "test_forwarded_k_key_enters_transcript_selection",
    "test_is_command_line_row_checks_tag",
    "test_load_block_tail_text_missing_log_marks_pruned",
    "test_o_toggles_expand_and_x_removes",
    "test_open_command_line_on_block_reports_pruned",
    "test_open_command_line_on_block_selects_existing",
    "test_p_opens_procs_with_focus_target",
    "test_procs_enter_routes_command_line_rows_to_panel",
    "test_procs_jump_focus_selects_block_on_open",
    "test_r_reruns_and_R_is_limited_to_declined_blocks",
    "test_real_R_press_reruns_declined_and_notices_otherwise",
    "test_real_i_a_colon_presses_return_to_insert",
    "test_refresh_pruned_flags_keeps_cached_tail",
    "test_remove_block_keeps_proc_record_and_falls_back",
    "test_render_selected_unseen_divider_and_rotation",
    "test_restore_missing_blocks_skips_known_procs",
    "test_select_first_last_and_empty_session",
    "test_select_restore_rows_enforces_limit_newest",
    "test_select_restore_rows_filters_and_orders",
    "test_selecting_clears_unseen_dot",
    "test_selection_moves_and_enters_at_last_block",
    "test_unselected_normal_input_keeps_vim_editing_and_redo",
    "test_v_loads_an_unloaded_tail_then_opens_pager",
    "test_v_opens_pager_for_selected_block",
    "test_y_and_Y_copy_output_and_command",
]
