"""Kill-and-edit launch barrier tests (facade over the split modules).

Focused and marked ``,x`` kill-and-edit mounts immediately; the launch waits.
See :mod:`tests.ace.tui.test_kill_and_edit_launch_barrier_mount` for the
immediate-mount tests and
:mod:`tests.ace.tui.test_kill_and_edit_launch_barrier_hold` for the
relaunch-barrier hold tests.
"""

from __future__ import annotations

from tests.ace.tui.test_kill_and_edit_launch_barrier_hold import (
    test_barrier_timeout_releases_held_launch_with_warning,
    test_cancelled_hold_drops_old_submit_and_new_prompt_launches,
    test_kill_last_launch_during_hold_drops_parked_launch,
    test_launch_held_while_barrier_pending_then_replays_once_settled,
    test_repeated_whole_bar_submit_while_held_replays_once,
    test_submit_resolved_launch_without_pending_barrier_submits_immediately,
    test_two_overlapping_barriers_replay_parked_launch_once,
)
from tests.ace.tui.test_kill_and_edit_launch_barrier_mount import (
    test_focused_dismiss_kill_and_edit_missing_raw_suffix_mounts_nothing,
    test_focused_dismiss_kill_and_edit_mounts_prompt_bar_immediately,
    test_focused_dismiss_kill_and_edit_rejected_submission_mounts_and_settles,
    test_focused_kill_and_edit_cancel_mounts_nothing_and_leaves_no_barrier,
    test_focused_kill_and_edit_mounts_prompt_bar_immediately,
    test_marked_bulk_kill_and_edit_mounts_prompt_stack_immediately,
)

__all__ = [
    "test_barrier_timeout_releases_held_launch_with_warning",
    "test_cancelled_hold_drops_old_submit_and_new_prompt_launches",
    "test_focused_dismiss_kill_and_edit_missing_raw_suffix_mounts_nothing",
    "test_focused_dismiss_kill_and_edit_mounts_prompt_bar_immediately",
    "test_focused_dismiss_kill_and_edit_rejected_submission_mounts_and_settles",
    "test_focused_kill_and_edit_cancel_mounts_nothing_and_leaves_no_barrier",
    "test_focused_kill_and_edit_mounts_prompt_bar_immediately",
    "test_kill_last_launch_during_hold_drops_parked_launch",
    "test_launch_held_while_barrier_pending_then_replays_once_settled",
    "test_marked_bulk_kill_and_edit_mounts_prompt_stack_immediately",
    "test_repeated_whole_bar_submit_while_held_replays_once",
    "test_submit_resolved_launch_without_pending_barrier_submits_immediately",
    "test_two_overlapping_barriers_replay_parked_launch_once",
]
