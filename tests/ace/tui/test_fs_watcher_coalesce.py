"""Coalesce, select-timeout, and noise-filter tests for ArtifactWatcher."""

from __future__ import annotations

import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.ace.tui.actions.event_refresh._artifact_paths import (
    artifact_watch_path_is_relevant,
)
from sase.ace.tui.util._fs_watcher_common import (
    IN_CREATE,
    IN_ISDIR,
    IN_MODIFY,
    IN_Q_OVERFLOW,
    is_ignored_watch_name,
)
from sase.ace.tui.util.fs_watcher import (
    DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S,
    PIPE_IDLE_FALLBACK_S,
    ArtifactWatcher,
)
from tests.ace.tui._fs_watcher_helpers import LINUX_ONLY, schedule_inline, wait

__all__ = [
    "test_collect_ignored_only_burst_returns_nothing",
    "test_collect_mixed_noise_keeps_real_path",
    "test_continuous_writes_dispatch_on_hard_deadline",
    "test_continuous_writes_dispatch_within_deadline",
    "test_default_coalesce_and_deadline_constants",
    "test_directory_create_stays_relevant_for_watch_growth",
    "test_fake_select_receives_deadline_derived_timeout",
    "test_idle_select_blocks_when_self_pipe_available",
    "test_idle_select_uses_fallback_without_self_pipe",
    "test_idle_watcher_does_not_timeout_wake_with_self_pipe",
    "test_ignored_only_burst_dispatches_nothing",
    "test_ignored_watch_names_cover_editor_and_sidecar_noise",
    "test_mixed_noise_linux_burst_keeps_real_path",
    "test_overflow_without_paths_fails_open_to_watch_roots",
    "test_trailing_coalesce_dispatches_after_quiet_window",
]


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
        schedule_callback=schedule_inline,
        coalesce_s=coalesce_s,
        deadline_s=deadline_s,
        is_relevant=is_relevant,
        clock=clock,
    )
    watcher._watch_paths_by_wd[1] = tmp_path  # noqa: SLF001
    watcher._wd_by_path[str(tmp_path)] = 1  # noqa: SLF001
    return watcher, changed


def test_ignored_watch_names_cover_editor_and_sidecar_noise() -> None:
    assert is_ignored_watch_name(".foo.swp")
    assert is_ignored_watch_name("foo.pyo")
    assert is_ignored_watch_name("beads.db-wal")
    assert is_ignored_watch_name("__pycache__")
    assert is_ignored_watch_name(".git")
    assert is_ignored_watch_name("file.txt~")
    assert not is_ignored_watch_name("agent_meta.json")
    assert not is_ignored_watch_name("live_reply.md")
    assert not is_ignored_watch_name("")


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
    data = _pack_event(1, IN_MODIFY, ".foo.swp") + _pack_event(
        1, IN_MODIFY, "output.log"
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
        _pack_event(1, IN_MODIFY, "output.log")
        + _pack_event(1, IN_MODIFY, ".x.swp")
        + _pack_event(1, IN_MODIFY, "agent_meta.json")
        + _pack_event(1, IN_MODIFY, "live_reply.md")
    )
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert agent_dir / "agent_meta.json" in paths
    assert agent_dir / "live_reply.md" in paths
    assert agent_dir / "output.log" not in paths
    assert agent_dir / ".x.swp" not in paths


def test_overflow_without_paths_fails_open_to_watch_roots(tmp_path: Path) -> None:
    watcher, changed = _detached_watcher(tmp_path, clock=_Clock())
    data = _pack_event(-1, IN_Q_OVERFLOW)
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert tmp_path in paths
    watcher._note_relevant_paths(paths)  # noqa: SLF001
    watcher._clock = lambda: 1002.0  # noqa: SLF001
    watcher._maybe_flush()
    assert changed == [(tmp_path,)]


def test_directory_create_stays_relevant_for_watch_growth(tmp_path: Path) -> None:
    watcher, _changed = _detached_watcher(tmp_path)
    data = _pack_event(1, IN_CREATE | IN_ISDIR, "20260828120000")
    paths = watcher._collect_relevant_events(data)  # noqa: SLF001
    assert tmp_path / "20260828120000" in paths


def test_default_coalesce_and_deadline_constants() -> None:
    assert DEFAULT_COALESCE_S == pytest.approx(0.2)
    assert DEFAULT_DISPATCH_DEADLINE_S == pytest.approx(1.0)


@LINUX_ONLY
def test_ignored_only_burst_dispatches_nothing(tmp_path: Path) -> None:
    changed: list[tuple[Path, ...]] = []

    def on_change(paths: tuple[Path, ...]) -> None:
        changed.append(paths)

    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=on_change,
        schedule_callback=schedule_inline,
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
        assert watcher.stats()["queued_dispatches"] == 0
    finally:
        watcher.stop()


@LINUX_ONLY
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
        schedule_callback=schedule_inline,
        coalesce_s=0.05,
        deadline_s=0.4,
        is_relevant=artifact_watch_path_is_relevant,
    )
    assert watcher.start() is True
    try:
        (agent_dir / "output.log").write_text("log")
        (agent_dir / ".x.swp").write_text("swap")
        (agent_dir / "agent_meta.json").write_text("{}")
        assert wait(fired.is_set, timeout=3.0)
        dispatched = {path for batch in changed for path in batch}
        assert agent_dir / "agent_meta.json" in dispatched
        assert agent_dir / "output.log" not in dispatched
        assert agent_dir / ".x.swp" not in dispatched
    finally:
        watcher.stop()


@LINUX_ONLY
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
        schedule_callback=schedule_inline,
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
        assert wait(fired.is_set, timeout=2.0)
        latency = first_dispatch[0] - started
        assert 0.15 <= latency <= 0.8
    finally:
        stop_writes.set()
        thread.join(timeout=1.0)
        watcher.stop()


@LINUX_ONLY
def test_idle_watcher_does_not_timeout_wake_with_self_pipe(tmp_path: Path) -> None:
    watcher = ArtifactWatcher(
        [tmp_path],
        on_change=lambda: None,
        schedule_callback=schedule_inline,
    )
    assert watcher.start() is True
    try:
        time.sleep(0.7)  # sase-test-wait: former 0.5 s idle select
        assert watcher.stats()["select_timeout_wakeups"] == 0
        assert watcher.stats()["ui_dispatches"] == 0
    finally:
        watcher.stop()
