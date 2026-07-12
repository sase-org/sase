"""Tests for the on_complete callback hook in agents async refresh."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        self._scheduled: list[Any] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append(self._run_agents_async_refresh)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))


@pytest.mark.asyncio
async def test_on_complete_fires_after_apply() -> None:
    app = _FakeApp()
    fired: list[str] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        del full_history
        fired.append("load")

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    def _cb() -> None:
        fired.append("cb")

    app._schedule_agents_async_refresh(on_complete=_cb)
    await app._run_agents_async_refresh()

    assert fired == ["load", "cb"]
    assert app._agents_refresh_pending_callbacks == []


@pytest.mark.asyncio
async def test_multiple_callbacks_fire_in_fifo_order() -> None:
    app = _FakeApp()
    fired: list[str] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        del full_history

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._schedule_agents_async_refresh(on_complete=lambda: fired.append("a"))
    app._schedule_agents_async_refresh(on_complete=lambda: fired.append("b"))
    app._schedule_agents_async_refresh(on_complete=lambda: fired.append("c"))

    await app._run_agents_async_refresh()

    assert fired == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_callback_exception_does_not_block_subsequent_callbacks() -> None:
    app = _FakeApp()
    fired: list[str] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        del full_history

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    def _bad() -> None:
        fired.append("bad")
        raise RuntimeError("boom")

    app._schedule_agents_async_refresh(on_complete=_bad)
    app._schedule_agents_async_refresh(on_complete=lambda: fired.append("good"))

    await app._run_agents_async_refresh()

    assert fired == ["bad", "good"]


@pytest.mark.asyncio
async def test_coalesced_followup_only_fires_its_own_callbacks() -> None:
    """A follow-up run scheduled while in-flight gets only its own callbacks.

    Callbacks registered before the in-flight run fire on that run; callbacks
    registered during the run get appended to the pending list and fire on
    the follow-up run.
    """
    app = _FakeApp()
    fired: list[str] = []
    cb_pending = lambda: fired.append("pending")  # noqa: E731

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        del full_history
        # During the in-flight run, schedule another refresh with a new cb
        app._schedule_agents_async_refresh(on_complete=cb_pending)

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._schedule_agents_async_refresh(on_complete=lambda: fired.append("first"))
    await app._run_agents_async_refresh()

    # First run's callback fired, follow-up run posted with pending callback
    assert fired == ["first"]
    assert app._agents_refresh_pending_callbacks == [cb_pending]
    assert app._scheduled.count(app._run_agents_async_refresh) == 2

    # Run the follow-up; the pending callback fires.
    await app._run_agents_async_refresh()
    assert fired == ["first", "pending"]


@pytest.mark.asyncio
async def test_delta_refresh_forwards_pending_full_history_request() -> None:
    """A Tier-2 request arriving mid-delta must not be downgraded to Tier 1.

    Regression test: the artifact-delta refresh's finally block used to clear
    the pending full-history flags without forwarding them, silently turning
    a queued full-history refresh into a Tier-1 load.
    """
    from pathlib import Path

    app = _FakeApp()

    async def _fake_delta_load(
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        del artifact_dirs, source, deleted_artifact_dirs
        # Simulate the user's full-history keybind racing the delta load.
        app._schedule_agents_async_refresh(
            full_history=True,
            full_history_reason="manual_full_history_refresh",
        )
        return True

    app._load_agent_artifact_delta_async = _fake_delta_load  # type: ignore[attr-defined]

    await app._run_agent_artifact_delta_refresh((Path("/tmp/agent-x"),), "watcher")

    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert (
        app._agents_refresh_scheduled_full_history_reason
        == "manual_full_history_refresh"
    )
