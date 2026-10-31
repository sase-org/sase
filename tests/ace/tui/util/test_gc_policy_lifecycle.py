"""Tests for GC policy installation, teardown, and input integration."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any

import pytest
from textual.screen import ModalScreen
from textual.widgets import Input, TextArea

from sase.ace.tui.actions._event_keyboard import EventKeyboardMixin
from sase.ace.tui.util import gc_policy, gc_telemetry
from sase.ace.tui.util.gc_policy import GCPolicy, install_gc_policy, uninstall_gc_policy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    Recorder,
    idle_policy,
)

modal_text_input_active = gc_policy._modal_text_input_active


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def collector() -> Collector:
    return Collector()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def active_guard() -> Iterator[None]:
    previous_active = gc_policy._active
    previous_providers = dict(gc_telemetry._heartbeat_providers)
    gc_policy._active = None
    try:
        yield
    finally:
        gc_policy._active = previous_active
        gc_telemetry._heartbeat_providers.clear()
        gc_telemetry._heartbeat_providers.update(previous_providers)


class _Modal(ModalScreen[None]):
    """Never-mounted modal screen carrying a stub focused widget."""

    def __init__(self, focused: Any) -> None:
        self._focused = focused

    @property
    def focused(self) -> Any:
        return self._focused


def test_thresholds_preserved_and_restored(
    collector: Collector, active_guard: None
) -> None:
    handle = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    assert handle is not None
    assert collector.threshold == (700, 10, gc_policy.RAISED_THRESHOLD2)
    assert handle.heartbeat_fields() == {"threshold_policy": "raised"}
    uninstall_gc_policy(handle)
    assert collector.threshold == (700, 10, 10)
    assert gc_policy._active is None


@pytest.mark.parametrize("threshold", [(700, 10), (700,), ()])
def test_unsupported_collector_shape_leaves_thresholds(
    threshold: tuple[int, ...], active_guard: None
) -> None:
    collector = Collector(threshold)
    handle = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    assert handle is not None
    try:
        assert collector.threshold == tuple(threshold)
        assert handle.heartbeat_fields() == {"threshold_policy": "unsupported"}
    finally:
        uninstall_gc_policy(handle)


def test_uninstall_stops_timer_unfreezes_and_unregisters(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    active_guard: None,
) -> None:
    stops: list[str] = []

    class _Timer:
        def stop(self) -> None:
            stops.append("stopped")

    app = SimpleNamespace(
        _last_input_mono=clock.now - 10.0,
        _mount_state_loads_done=True,
        _gc_telemetry=recorder,
        set_interval=lambda *args, **kwargs: _Timer(),
    )
    app._prompt_input_active = lambda: False
    handle = install_gc_policy(app=app, collector=collector)
    assert handle is not None
    assert handle.tick(clock.now) == "startup_freeze"
    assert gc_policy.HEARTBEAT_PROVIDER_NAME in gc_telemetry._heartbeat_providers
    uninstall_gc_policy(handle)
    assert stops == ["stopped"]
    assert collector.threshold == (700, 10, 10)
    assert collector.unfreezes == 1
    assert gc_policy.HEARTBEAT_PROVIDER_NAME not in gc_telemetry._heartbeat_providers
    assert gc_policy._active is None


def test_double_install_returns_active_handle(
    collector: Collector, active_guard: None
) -> None:
    first = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    second = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    assert first is not None
    assert second is first
    uninstall_gc_policy()


def test_kill_switch_disables_policy_but_nothing_else(
    collector: Collector,
    monkeypatch: pytest.MonkeyPatch,
    active_guard: None,
) -> None:
    monkeypatch.setenv(gc_policy.ENV_DISABLE, "1")
    assert install_gc_policy(app=object(), collector=collector) is None
    assert gc_policy._active is None
    assert collector.threshold == (700, 10, 10)


def test_trim_runs_at_most_every_ten_minutes(
    clock: Clock, collector: Collector, recorder: Recorder
) -> None:
    trims: list[float] = []
    policy = idle_policy(
        clock, collector, recorder, trim_runner=lambda: trims.append(clock.now)
    )
    assert policy.tick(clock.now) == "startup_freeze"
    assert trims == []
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert trims == [clock.now]
    # A minute later: collect again, but the trim cadence has not elapsed.
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert len(trims) == 1
    recorder.gen1 = 150
    clock.advance(601.0)
    assert policy.tick(clock.now) in ("idle", "backstop")
    assert len(trims) == 2


def test_trim_dispatch_runs_off_thread(
    monkeypatch: pytest.MonkeyPatch,
    active_guard: None,
) -> None:
    seen: list[str] = []
    first_done = threading.Event()
    second_done = threading.Event()

    def _recording_trim() -> bool:
        seen.append(threading.current_thread().name)
        (first_done if len(seen) == 1 else second_done).set()
        return True

    monkeypatch.setattr(gc_policy, "trim_allocator", _recording_trim)
    handle = install_gc_policy(app=None, tick_interval_s=0)
    assert handle is not None
    worker = gc_policy._trim_worker
    assert worker is not None and worker.is_alive()
    gc_policy._spawn_trim_thread()
    assert first_done.wait(timeout=5.0)
    gc_policy._spawn_trim_thread()
    assert second_done.wait(timeout=5.0)
    assert seen == [gc_policy.TRIM_THREAD_NAME, gc_policy.TRIM_THREAD_NAME]
    assert all(name != threading.current_thread().name for name in seen)
    assert gc_policy._trim_worker is worker
    uninstall_gc_policy(handle)
    assert not worker.is_alive()
    assert gc_policy._trim_worker is None


def test_combined_last_full_covers_recorder_and_own(
    clock: Clock, collector: Collector, recorder: Recorder
) -> None:
    policy = idle_policy(clock, collector, recorder)
    assert policy.combined_last_full_mono() is None
    recorder.last_full = 100.0
    assert policy.combined_last_full_mono() == 100.0
    policy._own_last_full_mono = 150.0
    assert policy.combined_last_full_mono() == 150.0


def test_modal_text_input_active() -> None:
    assert modal_text_input_active(SimpleNamespace(screen=object())) is False
    assert modal_text_input_active(SimpleNamespace(screen=_Modal(Input()))) is True
    assert modal_text_input_active(SimpleNamespace(screen=_Modal(TextArea()))) is True
    assert modal_text_input_active(SimpleNamespace(screen=_Modal(None))) is False

    class _Exploding:
        @property
        def screen(self) -> Any:
            raise RuntimeError("no screen")

    assert modal_text_input_active(_Exploding()) is False


def test_mouse_handlers_record_input_without_consuming() -> None:
    seen: list[str] = []

    class _Stub(EventKeyboardMixin):
        def __init__(self) -> None:
            self._last_input_action: str | None = None

        def _record_input_event(self) -> None:
            seen.append(self._last_input_action or "")

    stub = _Stub()
    stub.on_mouse_down(object())  # type: ignore[arg-type]
    stub.on_mouse_up(object())  # type: ignore[arg-type]
    stub.on_mouse_scroll_up(object())  # type: ignore[arg-type]
    stub.on_mouse_scroll_down(object())  # type: ignore[arg-type]
    assert seen == [
        "mouse_down",
        "mouse_up",
        "mouse_scroll_up",
        "mouse_scroll_down",
    ]


@pytest.mark.asyncio
async def test_testing_harness_does_not_auto_install() -> None:
    import sase.ace.testing as testing

    harness_startup = testing._startup

    assert harness_startup._ORIGINAL_INSTALL_GC_POLICY is gc_policy.install_gc_policy
    async with AsyncExitStack() as stack:
        harness_startup._install_fast_startup_overrides(stack)
        assert harness_startup._gc_policy.install_gc_policy(object()) is None


__all__ = [
    "test_thresholds_preserved_and_restored",
    "test_unsupported_collector_shape_leaves_thresholds",
    "test_uninstall_stops_timer_unfreezes_and_unregisters",
    "test_double_install_returns_active_handle",
    "test_kill_switch_disables_policy_but_nothing_else",
    "test_trim_runs_at_most_every_ten_minutes",
    "test_trim_dispatch_runs_off_thread",
    "test_combined_last_full_covers_recorder_and_own",
    "test_modal_text_input_active",
    "test_mouse_handlers_record_input_without_consuming",
    "test_testing_harness_does_not_auto_install",
]
