"""Smoke tests for the inotify-based :class:`ArtifactWatcher`."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.util.fs_watcher import (
    ArtifactWatcher,
    _libc,
    iter_startup_ace_run_shard_watch_paths,
)


_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux") or _libc() is None,
    reason="inotify is Linux-only and not available in this environment",
)


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    return predicate()


@_LINUX_ONLY
def test_watcher_dispatches_on_file_create(tmp_path: Path) -> None:
    """A new file inside a watched dir wakes the callback."""
    fired = threading.Event()
    changed: list[tuple[Path, ...]] = []

    def schedule(cb: Callable[[], None]) -> None:
        # Run the dispatcher inline — simulates Textual's call_from_thread
        cb()

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)
        fired.set()

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=schedule,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        (tmp_path / "new_file.json").write_text("{}")
        assert _wait(fired.is_set, timeout=3.0)
        assert any(tmp_path / "new_file.json" in paths for paths in changed)
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_watcher_start_does_not_walk_existing_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup installs bounded watches without scanning historical trees."""
    marker_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "20260505120000"
    marker_dir.mkdir(parents=True)

    def fail_rglob(self: Path, pattern: str):  # type: ignore[no-untyped-def]
        del self, pattern
        raise AssertionError("watcher startup must not recursively scan")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    watcher = ArtifactWatcher(
        [tmp_path / "proj" / "artifacts"],
        on_change=lambda: None,
        schedule_callback=schedule,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    watched_paths = set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
    assert tmp_path / "proj" / "artifacts" in watched_paths
    assert tmp_path / "proj" / "artifacts" / "ace-run" in watched_paths
    assert marker_dir not in watched_paths
    watcher.stop()


@_LINUX_ONLY
def test_watcher_dispatches_under_existing_workflow_dir(tmp_path: Path) -> None:
    """A marker write under a pre-existing workflow dir wakes the callback."""
    fired = threading.Event()
    changed: list[tuple[Path, ...]] = []
    artifacts_dir = tmp_path / "proj" / "artifacts"
    workflow_dir = artifacts_dir / "ace-run"
    workflow_dir.mkdir(parents=True)
    marker_dir = workflow_dir / "20260514193623"
    marker_path = marker_dir / "agent_meta.json"

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)
        fired.set()

    watcher = ArtifactWatcher(
        [artifacts_dir],
        on_change=on_change,
        schedule_callback=schedule,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        assert workflow_dir in set(watcher._watch_paths_by_wd.values())  # noqa: SLF001
        marker_dir.mkdir()
        assert _wait(
            lambda: marker_dir in set(watcher._watch_paths_by_wd.values()),  # noqa: SLF001
            timeout=3.0,
        )
        marker_path.write_text("{}")
        # Wait on the specific path rather than ``fired`` alone: a coalesced
        # dispatch from the preceding mkdir can land after a reset under
        # runner load and mask a missing marker write event.
        assert _wait(
            lambda: any(marker_path in paths for paths in changed),
            timeout=3.0,
        )
        assert fired.is_set()
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_watcher_dispatches_on_new_nested_marker_write(tmp_path: Path) -> None:
    """New nested agent marker directories are watched after startup."""
    fired = threading.Event()
    changed: list[tuple[Path, ...]] = []
    marker_dir = tmp_path / "proj" / "artifacts" / "ace-run" / "20260505120000"
    marker_path = marker_dir / "agent_meta.json"

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)
        fired.set()

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=schedule,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    try:
        marker_dir.mkdir(parents=True)
        assert _wait(
            lambda: marker_dir in set(watcher._watch_paths_by_wd.values()),  # noqa: SLF001
            timeout=3.0,
        )
        marker_path.write_text("{}")
        # Wait on the specific path rather than ``fired`` alone: a coalesced
        # dispatch from the preceding mkdir can land after a reset under
        # runner load and mask a missing marker write event.
        assert _wait(
            lambda: any(marker_path in paths for paths in changed),
            timeout=3.0,
        )
        assert fired.is_set()
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_watcher_coalesces_burst(tmp_path: Path) -> None:
    """A flurry of writes produces one dispatch, not N."""
    call_count = 0
    lock = threading.Lock()

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    def on_change() -> None:
        nonlocal call_count
        with lock:
            call_count += 1

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=schedule,
        coalesce_s=0.10,
    )
    assert watcher.start() is True
    try:
        for i in range(20):
            (tmp_path / f"f_{i}.json").write_text("{}")
        # Wait long enough for the coalesce window to elapse.
        time.sleep(0.30)  # sase-test-wait: fs watcher coalesce window
        # We expect 1 dispatch, possibly 2 if the final write landed
        # exactly on the boundary — never the 20+ that uncoalesced
        # forwarding would yield.
        with lock:
            count = call_count
        assert count <= 2
        assert count >= 1
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_watcher_stop_releases_thread(tmp_path: Path) -> None:
    """``stop()`` joins the worker thread within the documented bound."""

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule,
    )
    assert watcher.start() is True
    watcher.stop()
    # After stop(), a second stop() is a no-op and must not raise.
    watcher.stop()


def test_watcher_returns_false_when_no_paths_watchable(tmp_path: Path) -> None:
    """Non-existent paths produce a clean ``False`` and no thread."""
    bogus = tmp_path / "does-not-exist"

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    watcher = ArtifactWatcher(
        [bogus],
        on_change=lambda: None,
        schedule_callback=schedule,
    )
    assert watcher.start() is False


def test_watcher_drops_pending_flush_after_stop(tmp_path: Path) -> None:
    """A pending coalesced event must not schedule into a stopped app."""

    def schedule(cb: Callable[[], None]) -> None:
        raise AssertionError("stopped watcher should not dispatch callbacks")

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule,
        coalesce_s=0.01,
    )
    watcher._last_event_mono = time.monotonic() - 1.0
    watcher.stop()
    watcher._maybe_flush()


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


@_LINUX_ONLY
def test_watcher_startup_watches_live_shards_not_future_junk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 28, 12, 0, 0)
    monkeypatch.setattr("sase.ace.tui.util.fs_watcher.local_now", lambda: now)
    artifacts = tmp_path / "proj" / "artifacts"
    workflow = artifacts / "ace-run"
    live_month = _ace_run_tree(workflow, "202608")
    live_day = _ace_run_tree(workflow, "202608", "28")
    junk_month = _ace_run_tree(workflow, "213601")
    _ace_run_tree(workflow, "213601", "09")

    def schedule(cb: Callable[[], None]) -> None:
        cb()

    watcher = ArtifactWatcher(
        [artifacts],
        on_change=lambda: None,
        schedule_callback=schedule,
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


def _schedule_inline(cb: Callable[[], None]) -> None:
    cb()


def test_ensure_watches_and_prune_are_noop_before_start(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
    )
    assert watcher.ensure_watches([agent_dir]) == 0
    assert watcher.prune_agent_dir_watches([agent_dir]) == 0
    assert watcher._watch_paths_by_wd == {}  # noqa: SLF001


@_LINUX_ONLY
def test_ensure_watches_installs_dir_created_before_start(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
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


@_LINUX_ONLY
def test_ensure_watches_already_watched_path_does_not_consume_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.ace.tui.util.fs_watcher.MAX_INOTIFY_WATCHES", 1)
    other = tmp_path / "other"
    other.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
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


@_LINUX_ONLY
def test_ensure_watches_is_noop_after_stop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "20260828140403"
    agent_dir.mkdir()
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
        coalesce_s=0.02,
    )
    assert watcher.start() is True
    watcher.stop()
    assert watcher.ensure_watches([agent_dir]) == 0
    assert watcher._watch_paths_by_wd == {}  # noqa: SLF001


@_LINUX_ONLY
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
        schedule_callback=_schedule_inline,
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
