"""Event-driven auto-refresh dirty flags + sanity floor (Phase 7)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions._event_refresh import (
    AGENT_ARTIFACT_DELTA_QUEUE_LIMIT,
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
)
from sase.ace.tui.actions.event_handlers import (
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
    EventHandlersMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets.changespec_list import ChangeSpecList
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


def _make_agent(
    *,
    status: str = "RUNNING",
    cl_name: str = "agent",
    raw_suffix: str = "20260531120000",
    agent_type: AgentType = AgentType.RUNNING,
    parent_timestamp: str | None = None,
    step_type: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 5, 31, 12, 0, 0),
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        step_type=step_type,
    )


class _FakeAgentDetail:
    def __init__(self, refresh_calls: list[str]) -> None:
        self.panel_mode_label = "file"
        self.refreshed_agents: list[Agent] = []
        self._refresh_calls = refresh_calls

    def refresh_current_file(self, agent: Agent) -> None:
        self.refreshed_agents.append(agent)
        self._refresh_calls.append("file")


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
        self.current_idx = 0
        self.current_attempt_number = None
        self._agents: list[Agent] = []
        self._prompt_context = None
        self._approve_prompt_context = None
        self._plan_feedback_context = None
        self._mounted_prompt_bar = False
        self._fs_watcher = object() if watcher_active else None
        self._dirty_changespecs = False
        self._dirty_agents = False
        self._dirty_agent_artifact_dirs: tuple[Path, ...] = ()
        self._dirty_agent_artifact_fallback_reason: str | None = None
        self._dirty_axe = False
        self._dirty_notifications = False
        self._artifact_change_defer_pending = False
        self._last_full_sanity_refresh = time.monotonic()
        self._last_agents_load_mono = 0.0
        self._poll_agent_completions_result = False
        self.deferred_calls: list[tuple[float, Callable[[], Any]]] = []
        self.refresh_calls: list[str] = []
        self.refresh_requests: list[str] = []
        self.delta_requests: list[tuple[str, tuple[Path, ...]]] = []
        self._agents_refresh_trace_records: list[Any] = []
        self.agent_detail = _FakeAgentDetail(self.refresh_calls)

    def query(self, selector: type[PromptInputBar]) -> list[PromptInputBar]:
        if selector is PromptInputBar and self._mounted_prompt_bar:
            return [PromptInputBar()]
        return []

    def query_one(self, selector: str, _widget_type: object) -> Any:
        if selector == "#agent-detail-panel":
            return self.agent_detail
        raise LookupError(selector)

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self.deferred_calls.append((delay, callback))

    async def _load_axe_status_async(self) -> None:
        self.refresh_calls.append("axe")

    async def _poll_agent_completions(self) -> bool:
        self.refresh_calls.append("notifications")
        return self._poll_agent_completions_result

    async def _load_agents_async(self) -> None:
        self.refresh_calls.append("agents")

    async def _reload_and_reposition_async(self) -> None:
        self.refresh_calls.append("changespecs")

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.refresh_calls.append("schedule_agents")

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
    ) -> None:
        dirs = tuple(artifact_dirs)
        self.delta_requests.append((source, dirs))
        self.refresh_calls.append(f"delta:{source}:{len(dirs)}")

    def request_agents_refresh(
        self,
        source: str,
        *,
        debounce_ms: int = 150,
        latest_only: bool = True,
    ) -> None:
        del debounce_ms, latest_only
        self.refresh_calls.append(f"request_agents:{source}")
        self.refresh_requests.append(source)

    def _schedule_changespecs_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_changespecs")


@pytest.mark.asyncio
async def test_watcher_active_clean_flags_skip_all_refreshes() -> None:
    """Watcher active + every dirty flag clear + sanity-floor not due → no work."""
    app = _FakeApp(watcher_active=True)
    await app._on_auto_refresh()
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_watcher_active_clean_agents_tick_refreshes_selected_file_only() -> None:
    """Clean Agents-tab ticks refresh the selected live diff, not the loader."""
    app = _FakeApp(watcher_active=True)
    agent = _make_agent()
    app._agents = [agent]

    await app._on_auto_refresh()

    assert app.refresh_calls == ["file"]
    assert app.agent_detail.refreshed_agents == [agent]
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_completed_selected_agent() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent(status="DONE")]

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_mode_label", ["tools", "collapsed"])
async def test_watcher_active_clean_tick_skips_non_file_detail_modes(
    panel_mode_label: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app.agent_detail.panel_mode_label = panel_mode_label

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_attempt_pinned_detail() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app.current_attempt_number = 1

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag_name",
    ["_hint_mode_active", "_entry_jump_mode_active", "_accept_mode_active"],
)
async def test_watcher_active_clean_tick_skips_file_refresh_in_transient_modes(
    flag_name: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    setattr(app, flag_name, True)

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_file_refresh_while_loader_runs() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._agents_loading = True

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_load_does_not_refresh_file_panel() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._dirty_agents = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.agent_detail.refreshed_agents == []
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_runs_only_agent_path() -> None:
    """Only flag-set surfaces refresh when the watcher is active."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    await app._on_auto_refresh()
    # axe / notifications are still clean → no axe poll, no notification
    # poll; only the agents path runs.
    assert "axe" not in app.refresh_calls
    assert "notifications" not in app.refresh_calls
    assert "agents" in app.refresh_calls
    # agents tab → no changespec refresh.
    assert "changespecs" not in app.refresh_calls
    # Flag is cleared after the refresh consumed it.
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_dirty_notifications_polls_completions() -> None:
    """``_dirty_notifications`` gates the on-disk notification snapshot poll."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    await app._on_auto_refresh()
    assert "notifications" in app.refresh_calls
    assert "agents" not in app.refresh_calls
    assert "axe" not in app.refresh_calls
    assert app._dirty_notifications is False


@pytest.mark.asyncio
async def test_new_notification_schedules_agents_refresh_on_agents_tab() -> None:
    """Notification-triggered agent refreshes go through the debounce entry point."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications", "request_agents:notification"]
    assert app.refresh_requests == ["notification"]
    assert app._dirty_notifications is False
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_new_notification_does_not_schedule_agents_refresh_off_tab() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications"]


@pytest.mark.asyncio
async def test_new_notification_does_not_duplicate_due_agents_load() -> None:
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._dirty_agents = True
    app._poll_agent_completions_result = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications", "agents"]
    assert "schedule_agents" not in app.refresh_calls
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


@pytest.mark.asyncio
async def test_off_tab_dirty_agents_does_not_load_and_keeps_flag_set() -> None:
    """Auto-refresh while off the agents tab leaves the loader untouched.

    The dirty flag must persist so the next eligible tick (tab switch or
    sanity floor) picks up the deferred load.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_off_tab_sanity_tick_still_loads_agents() -> None:
    """Sanity-floor refresh runs the loader even when off the agents tab."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_agents = True
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "agents" in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_debounce_collapses_back_to_back_agent_loads() -> None:
    """Two auto-refresh ticks inside the debounce window only load once."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    # Re-arm the dirty flag (simulating inotify) and tick again well inside
    # the debounce window.
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    # Dirty flag stays set so the next eligible tick will retry.
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_debounce_window_clears_after_interval() -> None:
    """Once the debounce window elapses, the next tick loads again."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    # Pretend the previous load happened a full window ago.
    app._last_agents_load_mono = (
        time.monotonic() - AGENTS_LOAD_MIN_INTERVAL_SECONDS - 0.1
    )
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 2


@pytest.mark.asyncio
async def test_debounce_bypassed_by_sanity_floor() -> None:
    """A sanity-due tick must run the loader even inside the debounce window."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    app._last_agents_load_mono = time.monotonic()  # debounce active
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "agents" in app.refresh_calls


def test_artifact_change_marks_all_surfaces_dirty() -> None:
    """A coalesced inotify burst flips every dirty flag."""
    app = _FakeApp(watcher_active=True)
    app._on_artifact_change()
    assert app._dirty_changespecs is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_marks_only_agents_dirty_for_done_marker() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "a" / "done.json"

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path.parent,)
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app._dirty_changespecs is False
    assert app.refresh_calls == []


@pytest.mark.parametrize(
    "marker_name",
    ["workflow_state.json", "prompt_step_001.json"],
)
def test_artifact_change_marks_agents_dirty_for_loader_visible_markers(
    marker_name: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / marker_name
    )

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (path.parent,)
    assert app._dirty_changespecs is False
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_known_marker_change_schedules_artifact_delta_not_broad_load() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "done.json"
    )

    app._on_artifact_change((path,))
    await app._on_auto_refresh()

    assert app.refresh_calls == ["delta:watcher:1"]
    assert app.delta_requests == [("watcher", (path.parent,))]
    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None


@pytest.mark.asyncio
async def test_unknown_agent_path_uses_broad_auto_refresh_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    path = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )

    app._on_artifact_change((path,))
    await app._on_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.delta_requests == []
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unknown_watcher_path"
    )


@pytest.mark.asyncio
async def test_artifact_delta_queue_overflow_uses_broad_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    paths = tuple(
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / f"20260528{i:06d}"
        / "done.json"
        for i in range(AGENT_ARTIFACT_DELTA_QUEUE_LIMIT + 1)
    )

    app._on_artifact_change(paths)
    await app._on_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.delta_requests == []
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "dirty_queue_overflow"
    )


@pytest.mark.parametrize(
    "path",
    [
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000",
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "20260528120000",
    ],
)
def test_artifact_change_marks_agents_dirty_for_likely_agent_root_directory(
    path: Path,
) -> None:
    app = _FakeApp(watcher_active=True)

    app._on_artifact_change((path,))

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason == "unknown_watcher_path"
    assert app.refresh_calls == []


@pytest.mark.parametrize(
    "path",
    [
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "live_reply.md",
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
        / "generated"
        / "response.md",
    ],
)
def test_artifact_change_ignores_non_loader_artifact_content(path: Path) -> None:
    app = _FakeApp(watcher_active=True)

    app._on_artifact_change((path,))

    assert app._dirty_agents is False
    assert app._dirty_changespecs is False
    assert app._dirty_axe is False
    assert app.refresh_calls == []


def test_artifact_change_mixed_marker_and_content_marks_agents_dirty() -> None:
    app = _FakeApp(watcher_active=True)
    artifacts_dir = (
        Path.home()
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260528120000"
    )

    app._on_artifact_change(
        (
            artifacts_dir / "live_reply.md",
            artifacts_dir / "done.json",
            artifacts_dir / "generated" / "response.md",
        )
    )

    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (artifacts_dir,)
    assert app.refresh_calls == []


def test_artifact_change_schedules_only_changespecs_for_project_file() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "projects" / "sase" / "sase.gp"

    app._on_artifact_change((path,))

    assert app._dirty_changespecs is True
    assert app._dirty_axe is True
    assert app._dirty_agents is False
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_schedules_only_changespecs_for_bead_file() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.cwd() / "sdd" / "beads" / "sase-u.1.md"

    app._on_artifact_change((path,))

    assert app._dirty_changespecs is True
    assert app._dirty_agents is False
    assert app._dirty_axe is False
    assert app.refresh_calls == ["schedule_changespecs"]


def test_artifact_change_does_not_schedule_agent_load_for_notifications() -> None:
    app = _FakeApp(watcher_active=True)
    path = Path.home() / ".sase" / "notifications" / "notification.json"

    app._on_artifact_change((path,))

    assert app._dirty_notifications is True
    assert app._dirty_agents is False
    assert app.refresh_calls == []


def test_selection_navigation_does_not_trigger_refresh_work() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app.changespecs = [object()]
    app.current_idx = 0
    event = ChangeSpecList.SelectionChanged(0)

    app.on_change_spec_list_selection_changed(event)

    assert app.refresh_calls == []


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
    assert callback == app._on_artifact_change_deferred


def test_artifact_change_preserves_deferred_paths_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    changed = (
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "a" / "done.json",
    )

    app._on_artifact_change(changed)

    assert app._artifact_change_deferred_paths == changed

    app._plan_feedback_context = None
    app._on_artifact_change_deferred()

    assert app.refresh_calls == []


def test_artifact_change_dedupes_defer_timers_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    app._on_artifact_change()
    app._on_artifact_change()
    app._on_artifact_change()
    assert len(app.deferred_calls) == 1
    assert app._artifact_change_defer_pending is True
    assert app.refresh_calls == []


def test_artifact_change_deferred_reschedules_while_prompt_still_active() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    app._artifact_change_defer_pending = True
    app._on_artifact_change_deferred()
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    assert delay == PROMPT_INPUT_DEFER_SECONDS
    assert callback == app._on_artifact_change_deferred
    assert app._artifact_change_defer_pending is True
    assert app.refresh_calls == []


def test_artifact_change_deferred_resumes_refresh_after_prompt_closes() -> None:
    app = _FakeApp(watcher_active=True)
    app._artifact_change_defer_pending = True
    app._on_artifact_change_deferred()
    assert "schedule_changespecs" in app.refresh_calls
    assert "schedule_agents" not in app.refresh_calls
    assert app._artifact_change_defer_pending is False
