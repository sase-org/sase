"""Auto-refresh scheduling and artifact changes defer to the nav gate."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.event_refresh._surface_tokens import (
    SurfaceToken,
    SurfaceTokenSnapshot,
)
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _FakeApp(EventHandlersMixin):
    """Minimal stand-in that exercises only the gate-aware methods.

    The real :class:`AceApp` mixes :class:`EventHandlersMixin` with many
    other mixins; tests exercise the gate-aware deferral logic in
    isolation by stubbing the few collaborators it touches.
    """

    def __init__(self) -> None:
        self._nav_gate = NavigationGate(window_s=0.25)
        self.refresh_interval = 10
        self.sanity_refresh_interval = 300
        self._countdown_remaining = 10
        self._agents_loading = False
        self.current_tab = "agents"
        self._prompt_editor_suspended = False
        self._mounted_prompt_bar = False
        self.deferred_calls: list[tuple[float, Callable[[], Any]]] = []
        self.refresh_calls: list[str] = []
        self.countdown_calls: list[str] = []

    def query(self, selector: type[PromptInputBar]) -> list[PromptInputBar]:
        if selector is PromptInputBar and self._mounted_prompt_bar:
            return [PromptInputBar()]
        return []

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self.deferred_calls.append((delay, callback))

    def _probe_surface_tokens(self) -> SurfaceTokenSnapshot:
        def _token(surface: str) -> SurfaceToken:
            return SurfaceToken(
                surface=surface,
                parts=((f"/{surface}", True, 1, 1),),
            )

        return SurfaceTokenSnapshot(
            agents=_token("agents"),
            axe=_token("axe"),
            notifications=_token("notifications"),
            patches=_token("patches"),
            procs=_token("procs"),
        )

    async def _load_axe_status_async(self) -> None:
        self.refresh_calls.append("axe")

    async def _poll_agent_completions(self) -> bool:
        self.refresh_calls.append("notifications")
        return False

    async def _load_agents_async(self) -> None:
        self.refresh_calls.append("agents")

    async def _reload_and_reposition_async(self) -> None:
        self.refresh_calls.append("patches")

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.refresh_calls.append("schedule_agents")

    def _schedule_patches_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_patches")

    def _request_active_artifacts_refresh(self) -> None:
        self.refresh_calls.append("artifacts")

    def _update_agents_info_panel(self) -> None:
        self.countdown_calls.append("info")

    def _patch_agent_runtime_rows(self) -> None:
        self.countdown_calls.append("runtime")

    def _poll_starting_agent_transitions(self) -> None:
        self.countdown_calls.append("starting")


def test_record_jk_navigation_arms_gate() -> None:
    app = _FakeApp()
    assert not app._nav_gate.is_navigating()
    app._record_jk_navigation()
    assert app._nav_gate.is_navigating()


def test_countdown_tick_defers_agent_work_while_navigating() -> None:
    app = _FakeApp()
    app._record_jk_navigation()

    app._on_countdown_tick()

    assert app._countdown_remaining == 9
    assert app.countdown_calls == []


def test_countdown_tick_defers_agent_work_while_prompt_bar_mounted() -> None:
    app = _FakeApp()
    app._mounted_prompt_bar = True

    app._on_countdown_tick()

    assert app._countdown_remaining == 9
    assert app.countdown_calls == []


def test_countdown_tick_catches_up_after_prompt_typing_quiets() -> None:
    app = _FakeApp()
    app._mounted_prompt_bar = True

    app._on_countdown_tick()
    app._mounted_prompt_bar = False
    app._on_countdown_tick()

    assert app._countdown_remaining == 8
    assert app.countdown_calls == ["info", "runtime", "starting"]


def test_countdown_tick_defers_agent_work_while_prompt_editor_suspended() -> None:
    app = _FakeApp()
    app._prompt_editor_suspended = True

    app._on_countdown_tick()

    assert app._countdown_remaining == 9
    assert app.countdown_calls == []


def test_countdown_tick_updates_agents_when_navigation_is_idle() -> None:
    app = _FakeApp()

    app._on_countdown_tick()

    assert app._countdown_remaining == 9
    assert app.countdown_calls == ["info", "runtime", "starting"]


def test_auto_refresh_defers_when_navigating() -> None:
    app = _FakeApp()
    app._record_jk_navigation()
    app._on_auto_refresh()
    # No refresh work ran inline — the call rescheduled itself instead.
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    # Delay is the gate window remainder plus the 50 ms overshoot.
    assert 0.05 < delay <= 0.30
    assert callback == app._retry_auto_refresh


@pytest.mark.asyncio
async def test_auto_refresh_runs_inline_when_idle() -> None:
    app = _FakeApp()
    # Simulate "agents tab, no input modes, no in-flight load".
    app.current_tab = "agents"
    app._on_auto_refresh()
    await asyncio.gather(*list(app._pump_free_async_tasks))
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


def test_artifact_change_marks_dirty_and_dispatches_patches_when_idle() -> None:
    app = _FakeApp()
    app._on_artifact_change()
    assert app._dirty_agents is True
    assert app._dirty_patches is True
    assert app.refresh_calls == ["schedule_patches"]
    assert app.deferred_calls == []
