"""Startup shard, watch-tree, and ensure/prune tests for ArtifactWatcher."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.util.fs_watcher import ArtifactWatcher
from sase.core.agent_artifact_shards import iter_startup_ace_run_shard_watch_paths
from tests.ace.tui._fs_watcher_helpers import LINUX_ONLY, schedule_inline

__all__ = [
    "test_add_watch_tree_stops_at_agent_artifact_dir",
    "test_ensure_watches_already_watched_path_does_not_consume_budget",
    "test_ensure_watches_and_prune_are_noop_before_start",
    "test_ensure_watches_installs_dir_created_before_start",
    "test_ensure_watches_is_noop_after_stop",
    "test_idle_stop_returns_promptly_via_self_pipe",
    "test_prune_agent_dir_watches_removes_named_agent_dirs_only",
    "test_startup_shard_selection_keeps_live_and_drops_future_junk",
    "test_startup_shard_selection_spends_day_budget_newest_first",
    "test_startup_shard_selection_without_junk_keeps_newest_past_months",
    "test_watcher_startup_watches_live_shards_not_future_junk",
]


def _ace_run_tree(tmp_path: Path, *relative: str) -> Path:
    path = tmp_path.joinpath(*relative)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_startup_shard_selection_keeps_live_and_drops_future_junk(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 28, 12, 0, 0)
    workflow = tmp_path / "ace-run"
    live_month = _ace_run_tree(workflow, "202608")
    live_day = _ace_run_tree(workflow, "202608", "28")
    previous_month = _ace_run_tree(workflow, "202607")
    _ace_run_tree(workflow, "202607", "31")
    junk_month = _ace_run_tree(workflow, "213601")
    _ace_run_tree(workflow, "213601", "09")
    _ace_run_tree(workflow, "213510", "22")

    selected = list(iter_startup_ace_run_shard_watch_paths(workflow, now=now))

    assert live_month in selected
    assert live_day in selected
    assert previous_month in selected
    assert junk_month not in selected
    assert all(path.name != "213510" for path in selected)


def test_startup_shard_selection_without_junk_keeps_newest_past_months(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 28, 12, 0, 0)
    workflow = tmp_path / "ace-run"
    live_month = _ace_run_tree(workflow, "202608")
    live_day = _ace_run_tree(workflow, "202608", "28")
    previous_month = _ace_run_tree(workflow, "202607")
    older_month = _ace_run_tree(workflow, "202606")
    _ace_run_tree(workflow, "202607", "30")
    _ace_run_tree(workflow, "202606", "15")

    selected = list(iter_startup_ace_run_shard_watch_paths(workflow, now=now))

    assert live_month in selected
    assert live_day in selected
    assert previous_month in selected
    assert older_month not in selected


def test_startup_shard_selection_spends_day_budget_newest_first(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 3, 12, 0, 0)
    workflow = tmp_path / "ace-run"
    for day in ("01", "02", "03", "28"):
        _ace_run_tree(workflow, "202608", day)
    for day in ("29", "30", "31"):
        _ace_run_tree(workflow, "202607", day)

    selected = list(
        iter_startup_ace_run_shard_watch_paths(workflow, now=now, max_days=4)
    )
    day_names = [path.name for path in selected if len(path.name) == 2]

    assert day_names == ["03", "02", "01", "31"]
    assert (workflow / "202608" / "28") not in selected


def test_add_watch_tree_stops_at_agent_artifact_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day_dir = tmp_path / "28"
    agent_dir = day_dir / "20260828120000"
    nested = agent_dir / "commit_diffs"
    nested.mkdir(parents=True)
    watched: list[Path] = []

    def fake_add(
        self: ArtifactWatcher,
        libc: Any,
        fd: int,
        path: Path,
    ) -> int:
        del self, libc, fd
        watched.append(path)
        return 1

    monkeypatch.setattr(ArtifactWatcher, "_add_watch_path", fake_add)
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=lambda _cb: None,
    )
    installed = watcher._add_watch_tree(MagicMock(), 0, day_dir)  # noqa: SLF001

    assert installed == 2
    assert day_dir in watched
    assert agent_dir in watched
    assert nested not in watched


@LINUX_ONLY
def test_watcher_startup_watches_live_shards_not_future_junk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 28, 12, 0, 0)
    monkeypatch.setattr("sase.core.agent_artifact_shards.local_now", lambda: now)
    artifacts = tmp_path / "proj" / "artifacts"
    workflow = artifacts / "ace-run"
    live_month = _ace_run_tree(workflow, "202608")
    live_day = _ace_run_tree(workflow, "202608", "28")
    junk_month = _ace_run_tree(workflow, "213601")
    _ace_run_tree(workflow, "213601", "09")

    watcher = ArtifactWatcher(
        [artifacts],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        watched_paths = set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
        assert live_month in watched_paths
        assert live_day in watched_paths
        assert junk_month not in watched_paths
    finally:
        watcher.stop()


def test_ensure_watches_and_prune_are_noop_before_start(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
    )
    assert watcher.ensure_watches([agent_dir]) == 0
    assert watcher.prune_agent_dir_watches([agent_dir]) == 0
    assert watcher._watch_paths_by_wd == {}  # noqa: SLF001


@LINUX_ONLY
def test_ensure_watches_installs_dir_created_before_start(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        watched = set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
        assert tmp_path in watched
        assert agent_dir not in watched
        assert watcher.ensure_watches([agent_dir]) == 1
        assert agent_dir in set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
    finally:
        watcher.stop()


@LINUX_ONLY
def test_ensure_watches_already_watched_path_does_not_consume_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.ace.tui.util._fs_watcher_watches.MAX_INOTIFY_WATCHES", 1)
    other = tmp_path / "other"
    other.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        assert watcher.ensure_watches([tmp_path]) == 0
        assert tmp_path in set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
        assert watcher.ensure_watches([other]) == 0
        assert other not in set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
    finally:
        watcher.stop()


@LINUX_ONLY
def test_ensure_watches_is_noop_after_stop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    watcher.stop()
    assert watcher.ensure_watches([agent_dir]) == 0
    assert watcher._watch_paths_by_wd == {}  # noqa: SLF001


@LINUX_ONLY
def test_prune_agent_dir_watches_removes_named_agent_dirs_only(
    tmp_path: Path,
) -> None:
    shard = tmp_path / "28"
    shard.mkdir()
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    other_agent = tmp_path / "20260828140404"
    other_agent.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        assert watcher.ensure_watches([shard, agent_dir, other_agent]) == 3
        pruned = watcher.prune_agent_dir_watches([agent_dir, shard])
        assert pruned == 1
        watched = set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
        assert tmp_path in watched
        assert shard in watched
        assert other_agent in watched
        assert agent_dir not in watched
    finally:
        watcher.stop()


@LINUX_ONLY
def test_idle_stop_returns_promptly_via_self_pipe(tmp_path: Path) -> None:
    """An idle ``stop()`` wakes the worker instead of waiting out select."""
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
    )
    assert watcher.start() is True
    try:
        assert watcher._wake_r >= 0  # noqa: SLF001
        assert watcher._wake_w >= 0  # noqa: SLF001
        started = time.monotonic()
        watcher.stop()
        # Blocking idle select must wake via the self-pipe.
        assert time.monotonic() - started < 0.25
        assert watcher._fd == -1  # noqa: SLF001
        assert watcher._wake_r == -1  # noqa: SLF001
        assert watcher._wake_w == -1  # noqa: SLF001
    finally:
        watcher.stop()
