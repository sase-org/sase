"""Shared helpers for event handler dirty-flag tests."""

from __future__ import annotations

import time
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate
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

    def __init__(
        self,
        *,
        watcher_active: bool,
        sdd_beads_dir: Path | None = None,
    ) -> None:
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
        self._sdd_beads_dir = sdd_beads_dir
        self._dirty_patches = False
        self._dirty_agents = False
        self._dirty_agent_artifact_dirs: tuple[Path, ...] = ()
        self._dirty_deleted_agent_artifact_dirs: tuple[Path, ...] = ()
        self._dirty_agent_artifact_fallback_reason: str | None = None
        self._expected_agent_artifact_deletions: dict[str, float] = {}
        self._expected_agent_artifact_deletions_lock = threading.Lock()
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
        self.refresh_calls.append("patches")

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.refresh_calls.append("schedule_agents")

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> None:
        del deleted_artifact_dirs
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

    def _schedule_patches_async_refresh(self) -> None:
        self.refresh_calls.append("schedule_patches")
