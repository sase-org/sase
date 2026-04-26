"""``_on_auto_refresh`` and ``_on_artifact_change`` defer to the nav gate."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(EventHandlersMixin):
    """Minimal stand-in that exercises only the gate-aware methods.

    The real :class:`AceApp` mixes :class:`EventHandlersMixin` with many
    other mixins; tests exercise the gate-aware deferral logic in
    isolation by stubbing the few collaborators it touches.
    """

    def __init__(self) -> None:
        self._nav_gate = NavigationGate(window_s=0.25)
        self.refresh_interval = 10
        self._countdown_remaining = 10
        self._agents_loading = False
        self.current_tab = "agents"
        self.deferred_calls: list[tuple[float, Callable[[], Any]]] = []
        self.refresh_calls: list[str] = []

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self.deferred_calls.append((delay, callback))

    async def _load_axe_status_async(self) -> None:
        self.refresh_calls.append("axe")

    def _poll_agent_completions(self) -> None:
        self.refresh_calls.append("notifications")

    async def _load_agents_async(self) -> None:
        self.refresh_calls.append("agents")

    async def _reload_and_reposition_async(self) -> None:
        self.refresh_calls.append("changespecs")

    def _schedule_agents_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_agents")

    def _schedule_changespecs_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_changespecs")


def test_record_jk_navigation_arms_gate() -> None:
    app = _FakeApp()
    assert not app._nav_gate.is_navigating()
    app._record_jk_navigation()
    assert app._nav_gate.is_navigating()


@pytest.mark.asyncio
async def test_auto_refresh_defers_when_navigating() -> None:
    app = _FakeApp()
    app._record_jk_navigation()
    await app._on_auto_refresh()
    # No refresh work ran inline — the call rescheduled itself instead.
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    # Delay is the gate window remainder plus the 50 ms overshoot.
    assert 0.05 < delay <= 0.30
    assert callback == app._on_auto_refresh


@pytest.mark.asyncio
async def test_auto_refresh_runs_inline_when_idle() -> None:
    app = _FakeApp()
    # Simulate "agents tab, no input modes, no in-flight load".
    app.current_tab = "agents"
    await app._on_auto_refresh()
    # axe + notifications always run; agents runs because we're idle and
    # not in any input mode.  No deferred timer was scheduled.
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls
    assert app.deferred_calls == []


def test_artifact_change_defers_when_navigating() -> None:
    app = _FakeApp()
    app._record_jk_navigation()
    app._on_artifact_change()
    # Deferred — neither schedule was invoked.
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    _, callback = app.deferred_calls[0]
    assert callback == app._on_artifact_change


def test_artifact_change_dispatches_when_idle() -> None:
    app = _FakeApp()
    app._on_artifact_change()
    assert app.refresh_calls == ["schedule_agents", "schedule_changespecs"]
    assert app.deferred_calls == []
