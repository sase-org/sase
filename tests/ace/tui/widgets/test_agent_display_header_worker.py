"""Bounded latest-selection scheduling for detail-header enrichment."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import threading
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any
from unittest.mock import patch

import pytest
from sase.ace.tui.widgets.prompt_panel._agent_display_async_types import (
    DetailHeaderEnrichmentRequest,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_worker import (
    _AgentDetailHeaderEnrichmentService,
    app_header_enrichment_service,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.config.core import CONFIG_TOKEN_REFRESH_THREAD_NAME, current_config_token
from tests._config_cache_helpers import _reset_config_token_cache
from tests._conftest_runtime import (
    _drain_config_producers_then_refresh,
    _drain_config_token_refresh,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class _QueuedApp:
    def __init__(self) -> None:
        self._callbacks: deque[tuple[Callable[..., object], tuple[object, ...]]] = (
            deque()
        )
        self._lock = Lock()
        self._ready = Event()

    def call_from_thread(self, callback: Callable[..., object], *args: object) -> None:
        with self._lock:
            self._callbacks.append((callback, args))
            self._ready.set()

    def call_later(self, callback: Callable[..., object], *args: object) -> None:
        self.call_from_thread(callback, *args)

    def drain_queued(self) -> None:
        while True:
            with self._lock:
                if not self._callbacks:
                    self._ready.clear()
                    return
                callback, args = self._callbacks.popleft()
            callback(*args)

    def drain_until(self, predicate: Callable[[], bool], timeout: float = 5.0) -> None:
        deadline = monotonic() + timeout
        while not predicate():
            remaining = deadline - monotonic()
            assert remaining > 0, "timed out waiting for worker callbacks"
            self._ready.wait(remaining)
            while True:
                with self._lock:
                    if not self._callbacks:
                        self._ready.clear()
                        break
                    callback, args = self._callbacks.popleft()
                callback(*args)


class _WorkerPanel:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[tuple[object, ...]] = []
        self.cached: list[tuple[tuple[object, ...], DetailHeaderSummary]] = []
        self.painted: list[tuple[object, ...]] = []
        self.finished: list[
            tuple[tuple[object, ...], object, BaseException | None]
        ] = []
        self.active = 0
        self.max_active = 0
        self.fail_next = False
        self._lock = Lock()

    def _build_detail_header_summary(
        self,
        agent: Any,
        *,
        lanes: frozenset[Any],
        should_continue: Callable[[], bool],
        publish: Callable[[DetailHeaderSummary], None],
    ) -> DetailHeaderSummary:
        with self._lock:
            self.calls.append(agent.identity)
            call_number = len(self.calls)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("resolver failed")
            if call_number == 1:
                self.started.set()
                assert self.release.wait(5), "blocked resolver was not released"
                completed = DetailHeaderSummary(ready_lanes=lanes)
                publish(completed)
                return completed
            return DetailHeaderSummary(ready_lanes=lanes)
        finally:
            with self._lock:
                self.active -= 1

    def _publish_detail_header_summary(
        self, request: DetailHeaderEnrichmentRequest, summary: DetailHeaderSummary
    ) -> None:
        self.cached.append((request.agent_identity, summary))
        if request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            self.painted.append(request.agent_identity)

    def _finish_detail_header_summary(
        self,
        request: DetailHeaderEnrichmentRequest,
        summary: object,
        error: BaseException | None,
    ) -> None:
        self.finished.append((request.agent_identity, summary, error))
        if (
            error is None
            and isinstance(summary, DetailHeaderSummary)
            and request.is_current(
                request.agent_identity,
                request.generation,
                request.attempt_view_mode,
                request.attempt_pinned_number,
            )
        ):
            self.painted.append(request.agent_identity)


def _request(
    agent: Any,
    generation: int,
    current: list[tuple[tuple[object, ...] | None, int]],
) -> DetailHeaderEnrichmentRequest:
    return DetailHeaderEnrichmentRequest(
        agent=agent,
        agent_identity=agent.identity,
        lanes=frozenset({"artifacts"}),
        generation=generation,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda identity, requested_generation, *_: (
            current[0] == (identity, requested_generation)
        ),
    )


def test_rapid_a_b_a_selection_keeps_one_compute_and_latest_pending_request() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    first = make_agent(raw_suffix="first", status="RUNNING")
    middle = make_agent(raw_suffix="middle", status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(first.identity, 1)]
    try:
        service.submit(panel, _request(first, 1, current))
        assert panel.started.wait(5), "first resolver did not start"

        current[0] = (middle.identity, 2)
        service.submit(panel, _request(middle, 2, current))
        current[0] = (first.identity, 3)
        service.submit(panel, _request(first, 3, current))
        panel.release.set()
        app.drain_until(lambda: len(panel.finished) == 2)

        assert panel.calls == [first.identity, first.identity]
        assert panel.max_active == 1
        assert all(identity != middle.identity for identity in panel.calls)
        # The first completed lane remains reusable, while its stale request
        # never paints after A/B/A advanced the selection generation.
        assert len(panel.cached) == 1
        assert panel.painted == [first.identity]
        assert panel.finished[0][0] == first.identity
        assert panel.finished[0][2] is None
        assert panel.finished[1][0] == first.identity
    finally:
        panel.release.set()
        service.shutdown()


def test_resolver_error_does_not_poison_later_selection_work() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    panel.fail_next = True
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        app.drain_until(lambda: len(panel.finished) == 1)
        assert isinstance(panel.finished[0][2], RuntimeError)

        service.submit(panel, _request(agent, 2, current))
        app.drain_until(lambda: len(panel.finished) == 2)
        assert panel.finished[1][2] is None
        assert len(panel.cached) == 0
    finally:
        service.shutdown()


def test_panel_teardown_suppresses_late_worker_updates() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        service.cancel(panel, keep_identity=None)
        panel.release.set()
        app.drain_until(lambda: len(panel.calls) == 1 and service._active is None)
        assert panel.cached == []
        assert panel.painted == []
        assert panel.finished == []
    finally:
        panel.release.set()
        service.shutdown()


class _ConfigReadPanel:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[object] = []
        self.painted: list[object] = []
        self.finished: list[object] = []
        self.config_reads = 0

    def _build_detail_header_summary(
        self,
        agent: Any,
        *,
        lanes: frozenset[Any],
        should_continue: Callable[[], bool],
        publish: Callable[[DetailHeaderSummary], None],
    ) -> DetailHeaderSummary:
        del should_continue, publish
        self.calls.append(agent.identity)
        self.started.set()
        assert self.release.wait(5), "blocked resolver was not released"
        current_config_token()
        self.config_reads += 1
        return DetailHeaderSummary(ready_lanes=lanes)

    def _publish_detail_header_summary(
        self, request: DetailHeaderEnrichmentRequest, summary: DetailHeaderSummary
    ) -> None:
        self.painted.append(request.agent_identity)

    def _finish_detail_header_summary(
        self,
        request: DetailHeaderEnrichmentRequest,
        summary: object,
        error: BaseException | None,
    ) -> None:
        self.finished.append((request.agent_identity, summary, error))


class _DeadlockProbeApp:
    def call_later(self, callback: Callable[..., object], *args: object) -> None:
        del callback, args

    def call_from_thread(self, callback: Callable[..., object], *args: object) -> None:
        raise AssertionError("worker must not block on call_from_thread")


def _live_refresh_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == CONFIG_TOKEN_REFRESH_THREAD_NAME and thread.is_alive()
    ]


@contextmanager
def _stub_config_token() -> Iterator[None]:
    _reset_config_token_cache()
    with patch(
        "sase.config._cache._compute_current_config_token",
        return_value=("header-drain", 1),
    ):
        yield


def test_config_drain_before_header_completion_leaves_refresh_thread() -> None:
    """The old teardown order loses a late current_config_token."""
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _ConfigReadPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    with _stub_config_token():
        try:
            service.submit(panel, _request(agent, 1, current))
            assert panel.started.wait(5), "blocked resolver did not start"
            service.shutdown()
            _drain_config_token_refresh()
            assert not _live_refresh_threads()
            panel.release.set()
            deadline = monotonic() + 5
            while monotonic() < deadline and not _live_refresh_threads():
                sleep(0.01)  # sase-test-wait: poll for late refresh-thread start
            assert _live_refresh_threads()
        finally:
            panel.release.set()
            service.drain()
            _drain_config_token_refresh()


def test_header_drain_waits_for_resolver_before_config_drain() -> None:
    """Repaired cleanup joins the resolver, then the late refresh worker."""
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _ConfigReadPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    with _stub_config_token():
        try:
            service.submit(panel, _request(agent, 1, current))
            assert panel.started.wait(5), "blocked resolver did not start"
            service.shutdown()
            assert not service.is_running
            finished = Event()
            error: list[BaseException] = []

            def _drain() -> None:
                try:
                    service.drain()
                except BaseException as exc:  # noqa: BLE001 - captured for the test
                    error.append(exc)
                finally:
                    finished.set()

            waiter = Thread(target=_drain, daemon=True)
            waiter.start()
            assert not finished.wait(0.1)
            panel.release.set()
            assert finished.wait(5), "header drain did not finish after release"
            waiter.join(5)
            assert error == []
            assert panel.config_reads == 1
            _drain_config_token_refresh()
            assert not _live_refresh_threads()
        finally:
            panel.release.set()
            service.drain()
            _drain_config_token_refresh()


def test_producer_then_config_drain_joins_late_refresh_thread() -> None:
    """The isolation helper waits at the late-read boundary, then drains config."""
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _ConfigReadPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    with _stub_config_token():
        try:
            service.submit(panel, _request(agent, 1, current))
            assert panel.started.wait(5), "blocked resolver did not start"
            service.shutdown()

            def _release() -> None:
                sleep(0.02)  # sase-test-wait: lets drain reach the in-flight future
                panel.release.set()

            Thread(target=_release, daemon=True).start()
            _drain_config_producers_then_refresh()
            assert panel.config_reads == 1
            assert not _live_refresh_threads()
        finally:
            panel.release.set()
            service.drain()
            _drain_config_token_refresh()


def test_repeated_shutdown_and_drain_are_idempotent() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        panel.release.set()
        service.shutdown()
        service.shutdown()
        service.drain()
        service.drain()
        service.submit(panel, _request(agent, 2, current))
        app.drain_queued()
        assert len(panel.calls) == 1
    finally:
        panel.release.set()
        service.shutdown()
        service.drain()


def test_closed_service_with_inflight_work_stays_drainable() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        service.shutdown()
        assert not service.is_running
        assert service._future is not None
        panel.release.set()
        service.drain()
        app.drain_queued()
        assert panel.painted == []
        assert panel.finished == []
    finally:
        panel.release.set()
        service.drain()


def test_drain_timeout_retains_live_future() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        future = service._future
        assert future is not None
        with pytest.raises(RuntimeError, match="leaving the live future registered"):
            service.drain(timeout=0.05)
        assert service._future is future
        assert not future.done()
        panel.release.set()
        service.drain()
        assert future.done()
    finally:
        panel.release.set()
        service.shutdown()
        service.drain()


def test_drain_drops_pending_work() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    first = make_agent(raw_suffix="first", status="RUNNING")
    second = make_agent(raw_suffix="second", status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(first.identity, 1)]
    try:
        service.submit(panel, _request(first, 1, current))
        assert panel.started.wait(5), "first resolver did not start"
        current[0] = (second.identity, 2)
        service.submit(panel, _request(second, 2, current))
        panel.release.set()
        service.drain()
        app.drain_queued()
        assert panel.calls == [first.identity]
        assert all(identity != second.identity for identity in panel.calls)
    finally:
        panel.release.set()
        service.shutdown()
        service.drain()


def test_shutdown_suppresses_late_ui_paint_without_processing_the_loop() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        service.shutdown()
        panel.release.set()
        service.drain()
        assert panel.painted == []
        app.drain_queued()
        assert panel.painted == []
        assert panel.finished == []
    finally:
        panel.release.set()
        service.drain()


def test_drain_does_not_deadlock_when_call_from_thread_is_unsafe() -> None:
    app = _DeadlockProbeApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    agent = make_agent(status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(agent.identity, 1)]
    try:
        service.submit(panel, _request(agent, 1, current))
        assert panel.started.wait(5), "blocked resolver did not start"
        panel.release.set()
        service.drain()
        assert panel.calls == [agent.identity]
    finally:
        panel.release.set()
        service.shutdown()
        service.drain()


def test_drain_leaves_open_service_reusable() -> None:
    app = _QueuedApp()
    service = _AgentDetailHeaderEnrichmentService(app)
    panel = _WorkerPanel()
    first = make_agent(raw_suffix="first", status="RUNNING")
    second = make_agent(raw_suffix="second", status="RUNNING")
    current: list[tuple[tuple[object, ...] | None, int]] = [(first.identity, 1)]
    try:
        service.submit(panel, _request(first, 1, current))
        assert panel.started.wait(5), "first resolver did not start"
        panel.release.set()
        service.drain()
        app.drain_queued()
        assert not service._closed
        current[0] = (second.identity, 2)
        service.submit(panel, _request(second, 2, current))
        app.drain_until(lambda: len(panel.finished) == 1)
        assert panel.calls[-1] == second.identity
    finally:
        panel.release.set()
        service.shutdown()
        service.drain()


def test_closed_service_on_running_app_is_recreated() -> None:
    from textual.app import App

    class _Host:
        def __init__(self, app: App) -> None:
            self.app = app

    app = App()
    widget = _Host(app)
    first = app_header_enrichment_service(widget)
    assert first is not None
    first.shutdown()
    app._running = True
    second = app_header_enrichment_service(widget)
    try:
        assert second is not None
        assert second is not first
    finally:
        if second is not None:
            second.shutdown()
            second.drain()
        first.drain()


def test_closed_service_on_stopped_app_is_not_resurrected() -> None:
    from textual.app import App

    class _Host:
        def __init__(self, app: App) -> None:
            self.app = app

    app = App()
    widget = _Host(app)
    first = app_header_enrichment_service(widget)
    assert first is not None
    try:
        first.shutdown()
        assert app_header_enrichment_service(widget) is None
    finally:
        first.drain()
