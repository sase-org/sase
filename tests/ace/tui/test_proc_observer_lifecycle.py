"""Tests for ACE proc observer thread ownership and orphan cleanup."""

from __future__ import annotations

import threading

from typing import Any

from sase.ace.tui import AceApp
from sase.ace.tui.proc_observer import (
    PROC_OBSERVER_THREAD_NAME,
    ProcObserver,
    ProcObserverSnapshot,
    ProcProjection,
    stop_orphaned_proc_observers,
)


class _Owner:
    def __init__(self, *, is_running: bool) -> None:
        self.is_running = is_running
        self._proc_observer: ProcObserver | None = None


def _live_proc_observer_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == PROC_OBSERVER_THREAD_NAME and thread.is_alive()
    ]


def test_stop_orphaned_proc_observers_stops_unbound_started_observer() -> None:
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.start()
    try:
        assert observer.running
        stop_orphaned_proc_observers()
        assert not observer.running
        assert _live_proc_observer_threads() == []
    finally:
        observer.stop()


def test_stop_orphaned_proc_observers_keeps_running_owner_current_observer() -> None:
    owner = _Owner(is_running=True)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.bind_owner(owner)
    owner._proc_observer = observer
    observer.start()
    try:
        assert observer.running
        stop_orphaned_proc_observers()
        assert observer.running
    finally:
        observer.stop()


def test_stop_orphaned_proc_observers_stops_replaced_observer() -> None:
    owner = _Owner(is_running=True)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.bind_owner(owner)
    owner._proc_observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.start()
    try:
        assert observer.running
        stop_orphaned_proc_observers()
        assert not observer.running
    finally:
        observer.stop()


def test_constructing_ace_app_without_mount_is_orphaned() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)
    observer = app._proc_observer
    assert observer.running
    stop_orphaned_proc_observers()
    assert not observer.running
    assert _live_proc_observer_threads() == []


def test_init_proc_observer_stops_the_previous_thread() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)
    first = app._proc_observer
    assert first.running
    app._init_proc_observer()
    try:
        assert not first.running
        assert app._proc_observer.running
        assert app._proc_observer is not first
    finally:
        app._stop_proc_observer()


def test_observer_snapshot_callback_names_the_producing_observer() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)
    try:
        observer = app._proc_observer
        observer.stop()
        recorded: list[tuple[Any, ...]] = []

        def _record(fn: Any, *args: Any, **_kwargs: Any) -> None:
            recorded.append((fn, *args))

        app.call_from_thread = _record  # type: ignore[method-assign]
        snapshot = ProcObserverSnapshot(projection=ProcProjection())
        observer.on_snapshot(snapshot)
        assert recorded == [(app._apply_proc_observer_snapshot, snapshot, observer)]
    finally:
        app._stop_proc_observer()
