"""Event-driven auto-refresh dirty flags + sanity floor (Phase 7)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.event_handlers import (
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
    EventHandlersMixin,
)
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _FakeApp(EventHandlersMixin):
    """Minimal stand-in mirroring ``test_event_handlers_nav_gate``'s fake.

    Adds the watcher / dirty-flag knobs used by the Phase-7 auto-refresh
    gate so tests can drive the new event-driven path without spinning up
    a full :class:`AceApp`.
    """

    def __init__(self, *, watcher_active: bool) -> None:
        self._nav_gate = NavigationGate(window_s=0.25)
        self.refresh_interval = 10
        self._countdown_remaining = 10
        self._agents_loading = False
        self.current_tab = "agents"
        self._prompt_context = None
        self._approve_prompt_context = None
        self._plan_feedback_context = None
        self._mounted_prompt_bar = False
        self._fs_watcher = object() if watcher_active else None
        self._dirty_changespecs = False
        self._dirty_agents = False
        self._dirty_axe = False
        self._last_full_sanity_refresh = time.monotonic()
        self.deferred_calls: list[tuple[float, Callable[[], Any]]] = []
        self.refresh_calls: list[str] = []

    def query(self, selector: type[PromptInputBar]) -> list[PromptInputBar]:
        if selector is PromptInputBar and self._mounted_prompt_bar:
            return [PromptInputBar()]
        return []

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self.deferred_calls.append((delay, callback))

    async def _load_axe_status_async(self) -> None:
        self.refresh_calls.append("axe")

    async def _poll_agent_completions(self) -> None:
        self.refresh_calls.append("notifications")

    async def _load_agents_async(self) -> None:
        self.refresh_calls.append("agents")

    async def _reload_and_reposition_async(self) -> None:
        self.refresh_calls.append("changespecs")

    def _schedule_agents_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_agents")

    def _schedule_changespecs_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_changespecs")


@pytest.mark.asyncio
async def test_watcher_active_clean_flags_skip_all_refreshes() -> None:
    """Watcher active + every dirty flag clear + sanity-floor not due → no work."""
    app = _FakeApp(watcher_active=True)
    await app._on_auto_refresh()
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_runs_only_agent_path() -> None:
    """Only flag-set surfaces refresh when the watcher is active."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    await app._on_auto_refresh()
    # axe is still clean → no axe poll; agents+notifications run.
    assert "axe" not in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls
    # agents tab → no changespec refresh.
    assert "changespecs" not in app.refresh_calls
    # Flag is cleared after the refresh consumed it.
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_inactive_runs_full_refresh() -> None:
    """Without a watcher the auto-refresh path keeps polling every surface."""
    app = _FakeApp(watcher_active=False)
    await app._on_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_sanity_floor_forces_refresh_when_overdue() -> None:
    """A clean watcher state still reconciles once per sanity window."""
    app = _FakeApp(watcher_active=True)
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "agents" in app.refresh_calls


def test_artifact_change_marks_all_surfaces_dirty() -> None:
    """A coalesced inotify burst flips every dirty flag."""
    app = _FakeApp(watcher_active=True)
    app._on_artifact_change()
    assert app._dirty_changespecs is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    # Existing scheduling behavior preserved.
    assert app.refresh_calls == ["schedule_agents", "schedule_changespecs"]


@pytest.mark.asyncio
async def test_auto_refresh_skips_all_background_work_during_prompt_input() -> None:
    """Prompt entry should block axe, notifications, agents, and changespecs."""
    app = _FakeApp(watcher_active=False)
    app._prompt_context = object()
    await app._on_auto_refresh()
    assert app.refresh_calls == []
    assert app._countdown_remaining == app.refresh_interval


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context_name",
    ["_approve_prompt_context", "_plan_feedback_context"],
)
async def test_auto_refresh_treats_approval_and_feedback_as_prompt_input(
    context_name: str,
) -> None:
    app = _FakeApp(watcher_active=False)
    setattr(app, context_name, object())
    await app._on_auto_refresh()
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_auto_refresh_treats_mounted_prompt_bar_as_prompt_input() -> None:
    app = _FakeApp(watcher_active=False)
    app._mounted_prompt_bar = True
    await app._on_auto_refresh()
    assert app.refresh_calls == []


def test_artifact_change_defers_refresh_work_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    app._on_artifact_change()
    assert app._dirty_changespecs is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    assert delay == PROMPT_INPUT_DEFER_SECONDS
    assert callback == app._on_artifact_change
