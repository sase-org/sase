"""Smoke tests for the inotify-based :class:`ArtifactWatcher`."""

from __future__ import annotations

import struct
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.event_refresh._artifact_paths import (
    artifact_watch_path_is_relevant,
)
from sase.ace.tui.util.fs_watcher import (
    DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S,
    PIPE_IDLE_FALLBACK_S,
    ArtifactWatcher,
    _IN_CREATE,
    _IN_ISDIR,
    _IN_MODIFY,
    _IN_Q_OVERFLOW,
    _libc,
    _is_ignored_watch_name,
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
        deadline_s=0.01,
    )
    now = time.monotonic() - 1.0
    watcher._first_pending_mono = now
    watcher._last_event_mono = now
    watcher._pending_paths.add(tmp_path / "x.json")
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
    monkeypatch.setattr("sase.core.agent_artifact_shards.local_now", lambda: now)
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


@_LINUX_ONLY
def test_idle_stop_returns_promptly_via_self_pipe(tmp_path: Path) -> None:
    """An idle ``stop()`` wakes the worker instead of waiting out select."""
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
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


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _pack_event(wd: int, mask: int, name: str = "", cookie: int = 0) -> bytes:
    name_bytes = (name.encode("utf-8") + b"\0") if name else b""
    if name_bytes:
        pad = (16 - (len(name_bytes) % 16)) % 16
        name_bytes += b"\0" * pad
    return struct.pack("iIII", wd, mask, cookie, len(name_bytes)) + name_bytes


def _detached_watcher(
    tmp_path: Path,
    *,
    is_relevant: Callable[[Path], bool] | None = None,
    clock: Callable[[], float] | None = None,
    coalesce_s: float = 0.2,
    deadline_s: float = 1.0,
) -> tuple[ArtifactWatcher, list[tuple[Path, ...]]]:
    changed: list[tuple[Path, ...]] = []

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=_schedule_inline,
        coalesce_s=coalesce_s,
        deadline_s=deadline_s,
        is_relevant=is_relevant,
        clock=clock,
    )
    watcher._watch_paths_by_wd[1] = tmp_path  # noqa: SLF001
    watcher._wd_by_path[str(tmp_path)] = 1  # noqa: SLF001
    return watcher, changed


def test_ignored_watch_names_cover_editor_and_sidecar_noise() -> None:
    assert _is_ignored_watch_name(".foo.swp")
    assert _is_ignored_watch_name("foo.pyo")
    assert _is_ignored_watch_name("beads.db-wal")
    assert _is_ignored_watch_name("__pycache__")
    assert _is_ignored_watch_name(".git")
    assert _is_ignored_watch_name("file.txt~")
    assert not _is_ignored_watch_name("agent_meta.json")
    assert not _is_ignored_watch_name("live_reply.md")
    assert not _is_ignored_watch_name("")


def test_idle_select_blocks_when_self_pipe_available(tmp_path: Path) -> None:
    watcher, _changed = _detached_watcher(tmp_path)
    watcher._wake_r = 3  # noqa: SLF001
    assert watcher._pending_select_timeout() is None  # noqa: SLF001


def test_idle_select_uses_fallback_without_self_pipe(tmp_path: Path) -> None:
    watcher, _changed = _detached_watcher(tmp_path)
    watcher._wake_r = -1  # noqa: SLF001
    assert watcher._pending_select_timeout() == PIPE_IDLE_FALLBACK_S  # noqa: SLF001


def test_trailing_coalesce_dispatches_after_quiet_window(tmp_path: Path) -> None:
    clock = _Clock()
    watcher, changed = _detached_watcher(tmp_path, clock=clock)
    watcher._wake_r = 3  # noqa: SLF001
    relevant = {tmp_path / "agent_meta.json"}
    watcher._note_relevant_paths(relevant)  # noqa: SLF001
    assert watcher._pending_select_timeout() == pytest.approx(0.2)  # noqa: SLF001
    watcher._maybe_flush()
    assert changed == []
    clock.t += 0.2
    watcher._maybe_flush()
    assert changed == [tuple(sorted(relevant))]


def test_continuous_writes_dispatch_on_hard_deadline(tmp_path: Path) -> None:
    clock = _Clock()
    watcher, changed = _detached_watcher(
        tmp_path, clock=clock, coalesce_s=0.2, deadline_s=1.0
    )
    watcher._wake_r = 3  # noqa: SLF001
    relevant = tmp_path / "agent_meta.json"
    watcher._note_relevant_paths({relevant})  # noqa: SLF001
    for offset in (0.15, 0.4, 0.7, 0.95):
        clock.t = 1000.0 + offset
        watcher._note_relevant_paths({relevant})  # noqa: SLF001
        watcher._maybe_flush()
        assert changed == []
        remaining = watcher._pending_select_timeout()  # noqa: SLF001
        assert remaining is not None
        assert remaining == pytest.approx(min(0.2, 1.0 - offset))
    clock.t = 1001.0
    watcher._maybe_flush()
    assert changed == [(relevant,)]


def test_fake_select_receives_deadline_derived_timeout(tmp_path: Path) -> None:
    clock = _Clock()
    seen: list[float | None] = []

    def fake_select(
        readers: list[int],
        writers: list[int],
        errors: list[int],
        timeout: float | None = None,
    ) -> tuple[list[int], list[int], list[int]]:
        del readers, writers, errors
        seen.append(timeout)
        watcher._stop_event.set()  # noqa: SLF001
        return ([], [], [])

    watcher, _changed = _detached_watcher(tmp_path, clock=clock)
    watcher._fd = 7  # noqa: SLF001
    watcher._wake_r = 8  # noqa: SLF001
    watcher._select = fake_select  # noqa: SLF001
    watcher._note_relevant_paths({tmp_path / "agent_meta.json"})  # noqa: SLF001
    watcher._loop()  # noqa: SLF001
    assert seen == [pytest.approx(0.2)]


def test_collect_ignored_only_burst_returns_nothing(tmp_path: Path) -> None:
    agent_dir = (
        tmp_path / "proj" / "artifacts" / "ace-run" / "202608" / "28" / "20260828120000"
    )
    watcher, _changed = _detached_watcher(
        agent_dir, is_relevant=artifact_watch_path_is_relevant
    )
    data = _pack_event(1, _IN_MODIFY, ".foo.swp") + _pack_event(
        1, _IN_MODIFY, "output.log"
    )
    assert watcher._collect_relevant_events(data) == set()  # noqa: SLF001
    stats = watcher.stats()
    assert stats["raw_events"] == 2
    assert stats["ignored_events"] == 2
    assert stats["accepted_events"] == 0


def test_collect_mixed_noise_keeps_real_path(tmp_path: Path) -> None:
    agent_dir = (
        tmp_path / "proj" / "artifacts" / "ace-run" / "202608" / "28" / "20260828120000"
    )
    watcher, _changed = _detached_watcher(
        agent_dir, is_relevant=artifact_watch_path_is_relevant
    )
    watcher._watch_paths_by_wd[1] = agent_dir  # noqa: SLF001
    data = (
        _pack_event(1, _IN_MODIFY, "output.log")
        + _pack_event(1, _IN_MODIFY, ".x.swp")
        + _pack_event(1, _IN_MODIFY, "agent_meta.json")
        + _pack_event(1, _IN_MODIFY, "live_reply.md")
    )
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert agent_dir / "agent_meta.json" in paths
    assert agent_dir / "live_reply.md" in paths
    assert agent_dir / "output.log" not in paths
    assert agent_dir / ".x.swp" not in paths


def test_overflow_without_paths_fails_open_to_watch_roots(tmp_path: Path) -> None:
    watcher, changed = _detached_watcher(tmp_path, clock=_Clock())
    data = _pack_event(-1, _IN_Q_OVERFLOW)
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert tmp_path in paths
    watcher._note_relevant_paths(paths)  # noqa: SLF001
    watcher._clock = lambda: 1002.0  # noqa: SLF001
    watcher._maybe_flush()
    assert changed == [(tmp_path,)]


def test_directory_create_stays_relevant_for_watch_growth(tmp_path: Path) -> None:
    watcher, _changed = _detached_watcher(tmp_path)
    data = _pack_event(1, _IN_CREATE | _IN_ISDIR, "20260828120000")
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert tmp_path / "20260828120000" in paths


def test_default_coalesce_and_deadline_constants() -> None:
    assert DEFAULT_COALESCE_S == pytest.approx(0.2)
    assert DEFAULT_DISPATCH_DEADLINE_S == pytest.approx(1.0)


@_LINUX_ONLY
def test_ignored_only_burst_dispatches_nothing(tmp_path: Path) -> None:
    changed: list[tuple[Path, ...]] = []

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=_schedule_inline,
        coalesce_s=0.05,
        deadline_s=0.2,
        is_relevant=artifact_watch_path_is_relevant,
    )
    assert watcher.start() is True
    try:
        for i in range(12):
            (tmp_path / f".noise{i}.swp").write_text("x")
        time.sleep(0.35)  # sase-test-wait: ignored-only coalesce window
        assert changed == []
        assert watcher.stats()["ui_dispatches"] == 0
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_mixed_noise_linux_burst_keeps_real_path(tmp_path: Path) -> None:
    agent_dir = (
        tmp_path / "proj" / "artifacts" / "ace-run" / "202608" / "28" / "20260828120000"
    )
    agent_dir.mkdir(parents=True)
    changed: list[tuple[Path, ...]] = []
    fired = threading.Event()

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)
        fired.set()

    watcher = ArtifactWatcher(
        [agent_dir],
        on_change=on_change,
        schedule_callback=_schedule_inline,
        coalesce_s=0.05,
        deadline_s=0.4,
        is_relevant=artifact_watch_path_is_relevant,
    )
    assert watcher.start() is True
    try:
        (agent_dir / "output.log").write_text("log")
        (agent_dir / ".x.swp").write_text("swap")
        (agent_dir / "agent_meta.json").write_text("{}")
        assert _wait(fired.is_set, timeout=3.0)
        dispatched = {path for batch in changed for path in batch}
        assert agent_dir / "agent_meta.json" in dispatched
        assert agent_dir / "output.log" not in dispatched
        assert agent_dir / ".x.swp" not in dispatched
    finally:
        watcher.stop()


@_LINUX_ONLY
def test_continuous_writes_dispatch_within_deadline(tmp_path: Path) -> None:
    fired = threading.Event()
    first_dispatch: list[float] = []
    stop_writes = threading.Event()

    def on_change(paths: tuple[Path, ...]) -> None:
        del paths
        first_dispatch.append(time.monotonic())
        fired.set()

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=_schedule_inline,
        coalesce_s=0.2,
        deadline_s=0.4,
    )
    assert watcher.start() is True
    started = time.monotonic()

    def writer() -> None:
        i = 0
        while not stop_writes.is_set():
            (tmp_path / "agent_meta.json").write_text(str(i))
            i += 1
            time.sleep(0.05)  # sase-test-wait: sustained writer cadence

    thread = threading.Thread(target=writer, daemon=True)
    try:
        thread.start()
        assert _wait(fired.is_set, timeout=2.0)
        latency = first_dispatch[0] - started
        assert 0.15 <= latency <= 0.8
    finally:
        stop_writes.set()
        thread.join(timeout=1.0)
        watcher.stop()


@_LINUX_ONLY
def test_idle_watcher_does_not_timeout_wake_with_self_pipe(tmp_path: Path) -> None:
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=_schedule_inline,
    )
    assert watcher.start() is True
    try:
        time.sleep(0.7)  # sase-test-wait: former 0.5 s idle select
        assert watcher.stats()["select_timeout_wakeups"] == 0
        assert watcher.stats()["ui_dispatches"] == 0
    finally:
        watcher.stop()
