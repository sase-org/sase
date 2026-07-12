"""Tests for agents refresh scheduling coalescing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_active_source = "unknown"
        self._agents_refresh_debounce_armed = False
        self._agents_refresh_debounce_source = "unknown"
        self._scheduled: list[Any] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self.loaded_sources: list[str] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append(self._run_agents_async_refresh)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(
        self, *, full_history: bool = False, source: str = "unknown"
    ) -> None:
        del full_history
        self.loaded_sources.append(source)


@pytest.mark.asyncio
async def test_schedule_when_idle_spawns_once() -> None:
    app = _FakeApp()

    app._schedule_agents_async_refresh()

    assert app._scheduled == [app._run_agents_async_refresh]
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_pending is False
    assert app._agents_refresh_scheduled_source == "unknown"


@pytest.mark.asyncio
async def test_schedule_while_already_scheduled_sets_pending_only() -> None:
    app = _FakeApp()

    app._schedule_agents_async_refresh()
    app._schedule_agents_async_refresh()
    app._schedule_agents_async_refresh()

    assert app._scheduled == [app._run_agents_async_refresh]
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_pending is True
    assert app._agents_refresh_scheduled_source == "unknown"
    assert app._agents_refresh_pending_source == "unknown"


@pytest.mark.asyncio
async def test_debounced_request_forwards_source_to_scheduled_refresh() -> None:
    app = _FakeApp()

    app.request_agents_refresh("notification")

    assert len(app._timer_calls) == 1
    _, fire = app._timer_calls[0]
    fire()

    assert app._scheduled == [app._run_agents_async_refresh]
    assert app._agents_refresh_scheduled_source == "notification"

    await app._run_agents_async_refresh()
    assert app.loaded_sources == ["notification"]


@pytest.mark.asyncio
async def test_pending_refresh_records_follow_up_source() -> None:
    app = _FakeApp()

    app._schedule_agents_async_refresh(source="launch")
    app._schedule_agents_async_refresh(source="notification")

    assert app._agents_refresh_scheduled_source == "launch"
    assert app._agents_refresh_pending_source == "notification"

    await app._run_agents_async_refresh()

    assert app.loaded_sources == ["launch"]
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_source == "notification"


@pytest.mark.asyncio
async def test_run_refresh_queues_one_follow_up_when_pending() -> None:
    app = _FakeApp()

    async def _fake_load_agents_async() -> None:
        app._agents_refresh_pending = True

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]
    app._schedule_agents_async_refresh()

    await app._run_agents_async_refresh()

    # Follow-up run is posted once and pending flag is consumed.
    assert app._scheduled.count(app._run_agents_async_refresh) == 2
    assert app._agents_refresh_pending is False
    assert app._agents_refresh_scheduled is True


@pytest.mark.asyncio
async def test_slow_refresh_task_does_not_block_other_loop_callbacks() -> None:
    class _LiveTaskApp(_FakeApp):
        def _spawn_agents_refresh_task(self) -> None:
            AgentLoadingMixin._spawn_agents_refresh_task(self)

    app = _LiveTaskApp()
    started = asyncio.Event()
    release = asyncio.Event()
    heartbeat = asyncio.Event()

    async def _slow_load(
        *, full_history: bool = False, source: str = "unknown"
    ) -> None:
        del full_history, source
        started.set()
        await release.wait()

    app._load_agents_async = _slow_load  # type: ignore[method-assign]
    app._schedule_agents_async_refresh(source="slow-test")
    await asyncio.wait_for(started.wait(), timeout=0.5)
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
    assert app._agents_refresh_async_tasks

    release.set()
    await asyncio.gather(*list(app._agents_refresh_async_tasks))
