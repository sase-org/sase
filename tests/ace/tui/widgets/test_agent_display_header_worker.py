"""Bounded latest-selection scheduling for detail-header enrichment."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from threading import Event, Lock
from time import monotonic
from typing import Any

from sase.ace.tui.widgets.prompt_panel._agent_display_async_types import (
    DetailHeaderEnrichmentRequest,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_worker import (
    _AgentDetailHeaderEnrichmentService,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
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
