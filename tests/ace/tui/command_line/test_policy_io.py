"""Policy-I/O tests for the ``:`` Command Line."""

from ._policy_io_helpers import history_file

from ._policy_io_history import (
    test_remember_upserts_in_memory_without_disk,
    test_reopen_reuses_session_history_without_disk_reads,
    test_submit_and_exit_update_memory_without_reopen,
    test_note_exit_refreshes_without_bumping_count,
    test_submit_then_exit_counts_one_run_once,
)

from ._policy_io_workers import (
    test_procs_jump_reads_store_off_thread,
    test_palette_tip_marker_write_runs_off_loop,
    test_procs_jump_reads_off_thread_and_appends_on_ui_thread,
)

from ._policy_io_tail import (
    test_hidden_running_blocks_are_not_tailed,
    test_poll_once_ticks_running_elapsed,
    test_poll_once_ticks_submitting_without_log_read,
    test_poll_once_keeps_settled_elapsed_after_await,
    test_scrolled_out_running_block_is_not_tailed,
)

from ._policy_io_grammar import (
    grammar_handle,
    test_mounted_panel_shows_writes_chip,
)

__all__ = [
    "history_file",
    "test_remember_upserts_in_memory_without_disk",
    "test_reopen_reuses_session_history_without_disk_reads",
    "test_submit_and_exit_update_memory_without_reopen",
    "test_note_exit_refreshes_without_bumping_count",
    "test_submit_then_exit_counts_one_run_once",
    "test_procs_jump_reads_store_off_thread",
    "test_palette_tip_marker_write_runs_off_loop",
    "test_procs_jump_reads_off_thread_and_appends_on_ui_thread",
    "test_hidden_running_blocks_are_not_tailed",
    "test_poll_once_ticks_running_elapsed",
    "test_poll_once_ticks_submitting_without_log_read",
    "test_poll_once_keeps_settled_elapsed_after_await",
    "test_scrolled_out_running_block_is_not_tailed",
    "grammar_handle",
    "test_mounted_panel_shows_writes_chip",
]
