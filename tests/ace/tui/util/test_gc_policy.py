"""Tests for the idle-time full-GC policy."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import AsyncExitStack, contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from textual.screen import ModalScreen
from textual.widgets import Input, TextArea

from sase.ace.tui.actions._event_keyboard import EventKeyboardMixin
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util.gc_policy import (
    GCPolicy,
    _modal_text_input_active as modal_text_input_active,
    install_gc_policy,
    uninstall_gc_policy,
)


class _Clock:
    """Manually advanced monotonic clock for deterministic policy tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Collector:
    """Stub for the ``gc`` module surface the policy uses."""

    def __init__(self, threshold: tuple[int, ...] = (700, 10, 10)) -> None:
        self.threshold = tuple(threshold)
        self.counts = [0, 0, 0]
        self.collections = 0
        self.freezes = 0
        self.unfreezes = 0

    def get_threshold(self) -> tuple[int, ...]:
        return self.threshold

    def set_threshold(self, *values: int) -> None:
        self.threshold = tuple(values)

    def get_count(self) -> tuple[int, int, int]:
        return (self.counts[0], self.counts[1], self.counts[2])

    def collect(self) -> int:
        self.collections += 1
        return 0

    def freeze(self) -> None:
        self.freezes += 1

    def unfreeze(self) -> None:
        self.unfreezes += 1


class _Recorder:
    """Stub for the telemetry handle the policy reads the last full from."""

    def __init__(self) -> None:
        self.last_full: float | None = None
        self.gen1 = 0

    def last_full_collection_mono(self) -> float | None:
        return self.last_full

    def gen1_since_last_full(self) -> int:
        return self.gen1


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def collector() -> _Collector:
    return _Collector()


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def tags(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    @contextmanager
    def _recording(name: str) -> Iterator[None]:
        seen.append(name)
        yield

    monkeypatch.setattr(gc_policy, "gc_trigger", _recording)
    return seen


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


def _idle_policy(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
    *,
    last_input_ago: float = 10.0,
    trim_runner: Any = None,
) -> GCPolicy:
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - last_input_ago,
        prompt_active=lambda: False,
        navigating=lambda: False,
        modal_input_active=lambda: False,
        loads_done=lambda: True,
        collector=collector,
        recorder=recorder,
        trim_runner=(lambda: None) if trim_runner is None else trim_runner,
    )
    policy.apply_thresholds()
    return policy


def test_freeze_happens_once(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
    tags: list[str],
) -> None:
    cold = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
        loads_done=lambda: False,
        collector=collector,
        recorder=recorder,
        trim_runner=lambda: None,
    )
    assert cold.tick(clock.now) is None
    assert collector.collections == 0

    policy = _idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    assert collector.collections == 1
    assert collector.freezes == 1
    assert tags == ["startup_freeze"]

    # A later idle tick collects again but never re-freezes.
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 2
    assert collector.freezes == 1
    assert tags == ["startup_freeze", "idle"]


def test_no_collection_while_input_recent(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
) -> None:
    policy = _idle_policy(clock, collector, recorder, last_input_ago=1.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_while_prompt_active(
    clock: _Clock, collector: _Collector, recorder: _Recorder
) -> None:
    policy = _idle_policy(clock, collector, recorder)
    policy._prompt_active = lambda: True
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_while_navigating_or_modal(
    clock: _Clock, collector: _Collector, recorder: _Recorder
) -> None:
    policy = _idle_policy(clock, collector, recorder)
    policy._navigating = lambda: True
    assert policy.tick(clock.now) is None
    policy._navigating = lambda: False
    policy._modal_input_active = lambda: True
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_before_due(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
    tags: list[str],
) -> None:
    policy = _idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    # One minute later but nothing has piled up: no repeat collection.
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 1
    assert tags == ["startup_freeze"]


def test_collector_counter_marks_due_without_recorder(
    clock: _Clock, collector: _Collector
) -> None:
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
        loads_done=lambda: True,
        collector=collector,
        recorder=None,
        trim_runner=lambda: None,
    )
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    clock.advance(61.0)
    collector.counts = [0, 0, 100]
    assert policy.tick(clock.now) == "idle"


def test_time_backstop_relaxes_quiet_window(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
    tags: list[str],
) -> None:
    policy = _idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(301.0)
    # Only 1.5 s of quiet: too recent for "idle", fine for "backstop".
    idle_policy = _idle_policy(clock, collector, recorder, last_input_ago=1.5)
    idle_policy._froze_startup = True
    idle_policy._own_last_full_mono = policy._own_last_full_mono
    assert idle_policy.tick(clock.now) == "backstop"
    assert tags[-1] == "backstop"


def test_rss_backstop_relaxes_quiet_window(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
    tags: list[str],
) -> None:
    rss = {"now": 1_000}
    monkeypatch.setattr(gc_policy, "latest_rss_bytes", lambda: rss["now"])
    policy = _idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    assert policy._rss_at_last_full == 1_000

    rss["now"] = 1_000 + gc_policy.RSS_GROWTH_BACKSTOP_BYTES + 1
    recorder.gen1 = 150
    clock.advance(61.0)
    quiet_policy = _idle_policy(clock, collector, recorder, last_input_ago=1.5)
    quiet_policy._froze_startup = True
    quiet_policy._own_last_full_mono = policy._own_last_full_mono
    quiet_policy._rss_at_last_full = policy._rss_at_last_full
    assert quiet_policy.tick(clock.now) == "rss_backstop"
    assert tags[-1] == "rss_backstop"


def test_thresholds_preserved_and_restored(
    collector: _Collector, active_guard: None
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
    collector = _Collector(threshold)
    handle = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    assert handle is not None
    try:
        assert collector.threshold == tuple(threshold)
        assert handle.heartbeat_fields() == {"threshold_policy": "unsupported"}
    finally:
        uninstall_gc_policy(handle)


def test_uninstall_stops_timer_unfreezes_and_unregisters(
    clock: _Clock,
    collector: _Collector,
    recorder: _Recorder,
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
    collector: _Collector, active_guard: None
) -> None:
    first = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    second = install_gc_policy(app=None, collector=collector, tick_interval_s=0)
    assert first is not None
    assert second is first
    uninstall_gc_policy()


def test_kill_switch_disables_policy_but_nothing_else(
    collector: _Collector,
    monkeypatch: pytest.MonkeyPatch,
    active_guard: None,
) -> None:
    monkeypatch.setenv(gc_policy.ENV_DISABLE, "1")
    assert install_gc_policy(app=object(), collector=collector) is None
    assert gc_policy._active is None
    assert collector.threshold == (700, 10, 10)


def test_trim_runs_at_most_every_ten_minutes(
    clock: _Clock, collector: _Collector, recorder: _Recorder
) -> None:
    trims: list[float] = []
    policy = _idle_policy(
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
) -> None:
    seen: list[str] = []
    done = threading.Event()

    def _recording_trim() -> bool:
        seen.append(threading.current_thread().name)
        done.set()
        return True

    monkeypatch.setattr(gc_policy, "trim_allocator", _recording_trim)
    gc_policy._spawn_trim_thread()
    assert done.wait(timeout=5.0)
    assert seen == [gc_policy.TRIM_THREAD_NAME]
    assert seen[0] != threading.current_thread().name


def test_combined_last_full_covers_recorder_and_own(
    clock: _Clock, collector: _Collector, recorder: _Recorder
) -> None:
    policy = _idle_policy(clock, collector, recorder)
    assert policy.combined_last_full_mono() is None
    recorder.last_full = 100.0
    assert policy.combined_last_full_mono() == 100.0
    policy._own_last_full_mono = 150.0
    assert policy.combined_last_full_mono() == 150.0


class _Modal(ModalScreen[None]):
    """Never-mounted modal screen carrying a stub focused widget."""

    def __init__(self, focused: Any) -> None:
        self._focused = focused

    @property
    def focused(self) -> Any:
        return self._focused


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
    from sase.ace.testing import _startup as harness_startup

    assert harness_startup._ORIGINAL_INSTALL_GC_POLICY is gc_policy.install_gc_policy
    async with AsyncExitStack() as stack:
        harness_startup._install_fast_startup_overrides(stack)
        assert harness_startup._gc_policy.install_gc_policy(object()) is None
