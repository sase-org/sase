"""Compatibility facade for video inspect tests.

The concrete tests live in focused modules. Keep their original import path
available without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from .test_video_inspect_keys import (
    test_assemble_inspect_key_joins_arrow_bytes_split_across_reads,
    test_assemble_inspect_key_lone_escape_does_not_steal_next_key,
    test_assemble_inspect_key_times_out_without_input,
    test_decode_inspect_key_maps_arrow_sequences,
    test_read_inspect_key_does_not_flush_queued_keys,
    test_storyboard_auto_hides_on_small_panes,
    test_step_and_decile_math_clamps_at_both_ends,
    testformat_inspect_status_includes_bar_and_scrub_progress,
    testsnap_timestamp_uses_completed_scrub_track,
)
from .test_video_inspect_loop import (
    os_terminal_size,
    test_background_scrub_is_cancelled_on_exit,
    test_coalesced_l_presses_render_once_at_plus_five_seconds,
    test_decile_jump_seeks_and_renders,
    test_frame_step_uses_source_fps,
    test_inspect_outcomes_for_n_p_and_q,
    test_missing_kitten_keeps_inspect_alive,
    test_resize_re_renders_when_terminal_size_changes,
    test_sequence_loop_inspects_video_then_navigates_to_image,
    test_space_dispatch_matrix,
    test_storyboard_toggle_hides_strip,
    test_tab_preserves_playhead,
    test_tab_returns_to_ace_pane,
    test_zoom_re_renders,
)
from .test_video_inspect_session import (
    test_idle_status_writes_once_until_state_changes,
    test_missing_kitten_renders_cells_with_banner_and_notice,
    test_no_quiet_mode_with_injected_reader,
    test_quiet_mode_enter_exit_restores_termios,
    test_quiet_mode_suspends_around_motion_and_restores_on_exception,
    test_sequence_loop_passes_explicit_area_and_z_refreshes_size,
)

__all__ = (
    "os_terminal_size",
    "test_assemble_inspect_key_joins_arrow_bytes_split_across_reads",
    "test_assemble_inspect_key_lone_escape_does_not_steal_next_key",
    "test_assemble_inspect_key_times_out_without_input",
    "test_background_scrub_is_cancelled_on_exit",
    "test_coalesced_l_presses_render_once_at_plus_five_seconds",
    "test_decile_jump_seeks_and_renders",
    "test_decode_inspect_key_maps_arrow_sequences",
    "test_frame_step_uses_source_fps",
    "test_idle_status_writes_once_until_state_changes",
    "test_inspect_outcomes_for_n_p_and_q",
    "test_missing_kitten_keeps_inspect_alive",
    "test_missing_kitten_renders_cells_with_banner_and_notice",
    "test_no_quiet_mode_with_injected_reader",
    "test_quiet_mode_enter_exit_restores_termios",
    "test_quiet_mode_suspends_around_motion_and_restores_on_exception",
    "test_read_inspect_key_does_not_flush_queued_keys",
    "test_resize_re_renders_when_terminal_size_changes",
    "test_sequence_loop_inspects_video_then_navigates_to_image",
    "test_sequence_loop_passes_explicit_area_and_z_refreshes_size",
    "test_space_dispatch_matrix",
    "test_step_and_decile_math_clamps_at_both_ends",
    "test_storyboard_auto_hides_on_small_panes",
    "test_storyboard_toggle_hides_strip",
    "test_tab_preserves_playhead",
    "test_tab_returns_to_ace_pane",
    "test_zoom_re_renders",
    "testformat_inspect_status_includes_bar_and_scrub_progress",
    "testsnap_timestamp_uses_completed_scrub_track",
)

__test__ = False
