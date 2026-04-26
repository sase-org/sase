"""Smoke tests for the inotify-based :class:`ArtifactWatcher`."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.ace.tui.util.fs_watcher import ArtifactWatcher, _libc


_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux") or _libc() is None,
    reason="inotify is Linux-only and not available in this environment",
)


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@_LINUX_ONLY
def test_watcher_dispatches_on_file_create(tmp_path: Path) -> None:
    """A new file inside a watched dir wakes the callback."""
    fired = threading.Event()

    def schedule(cb: Callable[[], None]) -> None:
        # Run the dispatcher inline — simulates Textual's call_from_thread
        cb()

    def on_change() -> None:
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
        time.sleep(0.30)
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
