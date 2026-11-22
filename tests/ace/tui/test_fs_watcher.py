"""Smoke tests for the inotify-based :class:`ArtifactWatcher`.

Split facade: the tests now live in ``test_fs_watcher_dispatch``,
``test_fs_watcher_watches``, and ``test_fs_watcher_coalesce``. Shared
helpers live in :mod:`tests.ace.tui._fs_watcher_helpers`. This module
re-exports the public names so the original import path keeps working. It
collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_fs_watcher_coalesce import (
    test_collect_ignored_only_burst_returns_nothing,
    test_collect_mixed_noise_keeps_real_path,
    test_continuous_writes_dispatch_on_hard_deadline,
    test_continuous_writes_dispatch_within_deadline,
    test_default_coalesce_and_deadline_constants,
    test_directory_create_stays_relevant_for_watch_growth,
    test_fake_select_receives_deadline_derived_timeout,
    test_idle_select_blocks_when_self_pipe_available,
    test_idle_select_uses_fallback_without_self_pipe,
    test_idle_watcher_does_not_timeout_wake_with_self_pipe,
    test_ignored_only_burst_dispatches_nothing,
    test_ignored_watch_names_cover_editor_and_sidecar_noise,
    test_mixed_noise_linux_burst_keeps_real_path,
    test_overflow_without_paths_fails_open_to_watch_roots,
    test_trailing_coalesce_dispatches_after_quiet_window,
)
from tests.ace.tui.test_fs_watcher_dispatch import (
    test_watcher_coalesces_burst,
    test_watcher_dispatches_on_file_create,
    test_watcher_dispatches_on_new_nested_marker_write,
    test_watcher_dispatches_under_existing_workflow_dir,
    test_watcher_drops_pending_flush_after_stop,
    test_watcher_returns_false_when_no_paths_watchable,
    test_watcher_start_does_not_walk_existing_descendants,
    test_watcher_stop_releases_thread,
)
from tests.ace.tui.test_fs_watcher_watches import (
    test_add_watch_tree_stops_at_agent_artifact_dir,
    test_ensure_watches_already_watched_path_does_not_consume_budget,
    test_ensure_watches_and_prune_are_noop_before_start,
    test_ensure_watches_installs_dir_created_before_start,
    test_ensure_watches_is_noop_after_stop,
    test_idle_stop_returns_promptly_via_self_pipe,
    test_prune_agent_dir_watches_removes_named_agent_dirs_only,
    test_startup_shard_selection_keeps_live_and_drops_future_junk,
    test_startup_shard_selection_spends_day_budget_newest_first,
    test_startup_shard_selection_without_junk_keeps_newest_past_months,
    test_watcher_startup_watches_live_shards_not_future_junk,
)

__test__ = False

__all__ = [
    "test_add_watch_tree_stops_at_agent_artifact_dir",
    "test_collect_ignored_only_burst_returns_nothing",
    "test_collect_mixed_noise_keeps_real_path",
    "test_continuous_writes_dispatch_on_hard_deadline",
    "test_continuous_writes_dispatch_within_deadline",
    "test_default_coalesce_and_deadline_constants",
    "test_directory_create_stays_relevant_for_watch_growth",
    "test_ensure_watches_already_watched_path_does_not_consume_budget",
    "test_ensure_watches_and_prune_are_noop_before_start",
    "test_ensure_watches_installs_dir_created_before_start",
    "test_ensure_watches_is_noop_after_stop",
    "test_fake_select_receives_deadline_derived_timeout",
    "test_idle_select_blocks_when_self_pipe_available",
    "test_idle_select_uses_fallback_without_self_pipe",
    "test_idle_stop_returns_promptly_via_self_pipe",
    "test_idle_watcher_does_not_timeout_wake_with_self_pipe",
    "test_ignored_only_burst_dispatches_nothing",
    "test_ignored_watch_names_cover_editor_and_sidecar_noise",
    "test_mixed_noise_linux_burst_keeps_real_path",
    "test_overflow_without_paths_fails_open_to_watch_roots",
    "test_prune_agent_dir_watches_removes_named_agent_dirs_only",
    "test_startup_shard_selection_keeps_live_and_drops_future_junk",
    "test_startup_shard_selection_spends_day_budget_newest_first",
    "test_startup_shard_selection_without_junk_keeps_newest_past_months",
    "test_trailing_coalesce_dispatches_after_quiet_window",
    "test_watcher_coalesces_burst",
    "test_watcher_dispatches_on_file_create",
    "test_watcher_dispatches_on_new_nested_marker_write",
    "test_watcher_dispatches_under_existing_workflow_dir",
    "test_watcher_drops_pending_flush_after_stop",
    "test_watcher_returns_false_when_no_paths_watchable",
    "test_watcher_start_does_not_walk_existing_descendants",
    "test_watcher_startup_watches_live_shards_not_future_junk",
    "test_watcher_stop_releases_thread",
]
