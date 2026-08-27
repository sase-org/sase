"""Shared helpers for Agents-tab mark/bulk workflow tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._cleanup_procs import CleanupProcMixin
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.actions.agents._unread import AgentUnreadMixin
from sase.ace.tui.actions.agents._wait_resume import AgentWaitResumeMixin
from sase.ace.tui.actions.marking import MarkingMixin
from sase.ace.tui.modals.save_agent_group_modal import (
    SaveAgentGroupModal,
    SaveAgentGroupResult,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for marking tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeMarkApp(
    AgentMarkingMixin,
    TrackedProcRecorderMixin,
    CleanupProcMixin,
    AgentUnreadMixin,
    MarkingMixin,
):
    """Minimal app implementing just what the marking flow touches."""

    def __init__(self, agents: list[Agent], *, patch_result: bool = False) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_info_metrics_cache: tuple[Any, ...] | None = None
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: int = 0
        self.refresh_call_kwargs: list[dict[str, Any]] = []
        self.highlight_refresh_calls: int = 0
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self._scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.async_refreshes = 0
        self.async_refresh_sources: list[str] = []
        self.notification_count_refresh_calls = 0
        self.notification_refreshes_async = 0
        self.patches: list = []  # type: ignore[assignment]
        self.marked_indices: set[int] = set()
        self._artifacts_marked_targets: dict[str, set[Any]] = {"patches": set()}
        self._init_tracked_task_recorder()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refresh_calls += 1
        self.refresh_call_kwargs.append(
            {"list_changed": list_changed, "defer_detail": defer_detail}
        )

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _try_patch_patch_row(self, idx: int) -> bool:
        del idx
        return False

    def _update_info_panel(self) -> None:
        return

    def _refresh_panel_highlights(self) -> None:
        self.highlight_refresh_calls += 1

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1

    def _refresh_display(self) -> None:
        pass

    def _notify_after_refresh(
        self, message: str, *, severity: str = "information"
    ) -> None:
        self.notify(message, severity=severity)

    def call_later(self, callback: Any, *args: Any) -> None:
        self._scheduled.append((callback, args))

    async def _refresh_notification_count_async(self) -> None:
        self.notification_refreshes_async += 1

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.async_refreshes += 1
        self.async_refresh_sources.append(source)

    def _apply_dismissal_in_memory(self, agents: list[Agent]) -> None:
        removed = {agent.identity for agent in agents}
        self._agents = [a for a in self._agents if a.identity not in removed]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in removed
        ]
        self._dismissed_agent_objects.extend(agents)

    def _agents_visible_order(self) -> list[int]:
        from sase.ace.tui.models.agent_groups import build_agent_tree

        tree = build_agent_tree(self._agents, fold_registry=self._group_fold_registry)
        return [
            entry.agent_idx
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _panel_navigation_stops(self) -> list[tuple[str, int | tuple[str, ...]]]:
        from sase.ace.tui.models.agent_groups import build_agent_tree

        tree = build_agent_tree(self._agents, fold_registry=self._group_fold_registry)
        stops: list[tuple[str, int | tuple[str, ...]]] = []
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    stops.append(("banner", entry.group.group_key))
            elif entry.kind == "agent" and entry.agent_idx is not None:
                stops.append(("agent", entry.agent_idx))
        return stops

    def _panel_navigation_stop_maps(
        self,
    ) -> tuple[dict[int, int], dict[tuple[str, ...], int]]:
        agent_positions: dict[int, int] = {}
        banner_positions: dict[tuple[str, ...], int] = {}
        for pos, (kind, payload) in enumerate(self._panel_navigation_stops()):
            if kind == "agent":
                assert isinstance(payload, int)
                agent_positions[payload] = pos
            else:
                assert isinstance(payload, tuple)
                banner_positions[payload] = pos
        return agent_positions, banner_positions

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_kill_agent(self, agent: Agent) -> None:
        self._agents = [a for a in self._agents if a.identity != agent.identity]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity != agent.identity
        ]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        ids = {a.identity for a in agents}
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        ids = {a.identity for a in killable}
        ids.update(a.identity for a in dismissable or [])
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]
        self._reset_marked_agents()


def _confirm_save_modal(app: _FakeMarkApp, *, name: str | None = None) -> None:
    assert app.pushed_modals, "Save modal not registered"
    assert isinstance(app.pushed_modals[-1], SaveAgentGroupModal)
    callback = app.pushed_callbacks[-1]
    assert callback is not None
    callback(SaveAgentGroupResult(name=name))


def _cancel_save_modal(app: _FakeMarkApp) -> None:
    assert app.pushed_modals, "Save modal not registered"
    callback = app.pushed_callbacks[-1]
    assert callback is not None
    callback(None)


class _FakeWaitApp(AgentWaitResumeMixin, AgentMarkingMixin, MarkingMixin):
    """Minimal app implementing what action_wait_for_agent touches."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self.notifications: list[tuple[str, str]] = []
        self.prompt_bar_calls: list[dict[str, Any]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _show_prompt_input_bar_for_home(
        self,
        *,
        initial_text: str = "",
        display_name: str | None = None,
        history_sort_key: str | None = None,
    ) -> None:
        self.prompt_bar_calls.append(
            {
                "initial_text": initial_text,
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )
