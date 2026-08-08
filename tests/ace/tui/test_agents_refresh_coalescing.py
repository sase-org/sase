"""Tests for agents refresh scheduling coalescing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions._event_refresh import AGENT_ARTIFACT_DELTA_QUEUE_LIMIT
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_active_source = "unknown"
        self._agents_artifact_delta_scheduled = None
        self._agents_artifact_delta_pending = None
        self._agents_refresh_debounce_armed = False
        self._agents_refresh_debounce_source = "unknown"
        self._agent_search_query = ""
        self._scheduled: list[Any] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self.loaded_sources: list[str] = []
        self.loaded_full_history: list[bool] = []
        self.delta_loads: list[tuple[str, tuple[Path, ...], tuple[Path, ...]]] = []
        self._agents_refresh_trace_records: list[Any] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append(self._run_agents_async_refresh)

    def _spawn_agent_artifact_delta_refresh_task(self, request: Any) -> None:
        self._scheduled.append(("delta", request))

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(
        self, *, full_history: bool = False, source: str = "unknown"
    ) -> None:
        self.loaded_full_history.append(full_history)
        self.loaded_sources.append(source)

    async def _load_agent_artifact_delta_async(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        self.delta_loads.append(
            (source, tuple(artifact_dirs), tuple(deleted_artifact_dirs or ()))
        )
        return True


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


def test_exact_delta_requests_merge_before_first_task_runs() -> None:
    app = _FakeApp()
    first = Path("/tmp/agent-a")
    second = Path("/tmp/agent-b")

    app._schedule_agent_artifact_delta_refresh([first], source="watcher")
    app._schedule_agent_artifact_delta_refresh(
        [first, second],
        source="starting_poll",
        deleted_artifact_dirs=[second],
    )

    assert [entry[0] for entry in app._scheduled] == ["delta"]
    request = app._agents_artifact_delta_scheduled
    assert tuple(request.artifact_dirs) == (first, second)
    assert tuple(request.deleted_artifact_dirs) == (second,)
    assert request.source == "starting_poll"
    assert {record.stage for record in app._agents_refresh_trace_records} >= {
        "scheduled",
        "coalesced",
    }


@pytest.mark.asyncio
async def test_exact_delta_survives_broad_load_contention() -> None:
    app = _FakeApp()
    first = Path("/tmp/agent-a")
    second = Path("/tmp/agent-b")
    fired: list[str] = []

    async def _load_agents_async(
        *, full_history: bool = False, source: str = "unknown"
    ) -> None:
        app.loaded_full_history.append(full_history)
        app.loaded_sources.append(source)
        app._schedule_agent_artifact_delta_refresh(
            [first],
            source="starting_poll",
            on_complete=lambda: fired.append("first"),
        )
        app._schedule_agent_artifact_delta_refresh(
            [first, second],
            source="watcher",
            on_complete=lambda: fired.append("second"),
            deleted_artifact_dirs=[second],
        )

    app._load_agents_async = _load_agents_async  # type: ignore[method-assign]

    app._schedule_agents_async_refresh(source="launch")
    await app._run_agents_async_refresh()

    assert app.loaded_sources == ["launch"]
    assert app._agents_refresh_scheduled is False
    request = app._agents_artifact_delta_scheduled
    assert request is not None
    assert tuple(request.artifact_dirs) == (first, second)
    assert tuple(request.deleted_artifact_dirs) == (second,)
    assert fired == []
    assert all(
        record.fallback_reason != "delta_read_failure"
        for record in app._agents_refresh_trace_records
    )

    await app._run_agent_artifact_delta_refresh(request)

    assert app.delta_loads == [("watcher", (first, second), (second,))]
    assert fired == ["first", "second"]


@pytest.mark.asyncio
async def test_delta_load_contention_keeps_one_trailing_exact_batch() -> None:
    app = _FakeApp()
    first = Path("/tmp/agent-a")
    second = Path("/tmp/agent-b")
    third = Path("/tmp/agent-c")

    async def _load_agent_artifact_delta_async(
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        app.delta_loads.append(
            (source, tuple(artifact_dirs), tuple(deleted_artifact_dirs or ()))
        )
        if tuple(artifact_dirs) == (first,):
            app._schedule_agent_artifact_delta_refresh([second], source="watcher")
            app._schedule_agent_artifact_delta_refresh(
                [second, third],
                source="starting_poll",
            )
        return True

    app._load_agent_artifact_delta_async = _load_agent_artifact_delta_async  # type: ignore[method-assign]

    app._schedule_agent_artifact_delta_refresh([first], source="watcher")
    await app._run_agent_artifact_delta_refresh(app._agents_artifact_delta_scheduled)

    trailing = app._agents_artifact_delta_scheduled
    assert app.delta_loads == [("watcher", (first,), ())]
    assert app._agents_refresh_scheduled is False
    assert tuple(trailing.artifact_dirs) == (second, third)

    await app._run_agent_artifact_delta_refresh(trailing)
    assert app.delta_loads[-1] == ("starting_poll", (second, third), ())


@pytest.mark.asyncio
async def test_full_history_request_racing_delta_precedes_newer_exact_work() -> None:
    app = _FakeApp()
    first = Path("/tmp/agent-a")
    second = Path("/tmp/agent-b")

    async def _load_agent_artifact_delta_async(
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        del artifact_dirs, source, deleted_artifact_dirs
        app._schedule_agents_async_refresh(
            source="manual",
            full_history=True,
            full_history_reason="manual_full_history_refresh",
        )
        app._schedule_agent_artifact_delta_refresh([second], source="watcher")
        return True

    app._load_agent_artifact_delta_async = _load_agent_artifact_delta_async  # type: ignore[method-assign]

    app._schedule_agent_artifact_delta_refresh([first], source="watcher")
    await app._run_agent_artifact_delta_refresh(app._agents_artifact_delta_scheduled)

    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert app._agents_artifact_delta_pending is not None

    await app._run_agents_async_refresh()

    assert app.loaded_sources == ["manual"]
    assert app.loaded_full_history == [True]
    assert tuple(app._agents_artifact_delta_scheduled.artifact_dirs) == (second,)


@pytest.mark.asyncio
async def test_delta_failure_schedules_one_broad_recovery_with_callback() -> None:
    app = _FakeApp()
    fired: list[str] = []

    async def _failing_delta_load(
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        del artifact_dirs, source, deleted_artifact_dirs
        raise RuntimeError("boom")

    app._load_agent_artifact_delta_async = _failing_delta_load  # type: ignore[method-assign]

    app._schedule_agent_artifact_delta_refresh(
        [Path("/tmp/agent-a")],
        source="watcher",
        on_complete=lambda: fired.append("done"),
    )
    await app._run_agent_artifact_delta_refresh(app._agents_artifact_delta_scheduled)

    assert app._agents_refresh_scheduled is True
    assert fired == []
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "delta_read_failure"
    ] == ["delta_read_failure"]

    await app._run_agents_async_refresh()
    assert fired == ["done"]


@pytest.mark.asyncio
async def test_exact_delta_overflow_schedules_one_broad_recovery() -> None:
    app = _FakeApp()
    fired: list[str] = []
    paths = [
        Path(f"/tmp/agent-{i}") for i in range(AGENT_ARTIFACT_DELTA_QUEUE_LIMIT + 1)
    ]

    app._schedule_agent_artifact_delta_refresh(
        paths,
        source="watcher",
        on_complete=lambda: fired.append("done"),
    )

    assert app._agents_refresh_scheduled is True
    assert app._agents_artifact_delta_scheduled is None
    assert [
        record.fallback_reason
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "dirty_queue_overflow"
    ] == ["dirty_queue_overflow"]

    await app._run_agents_async_refresh()
    assert fired == ["done"]
