"""Shared harnesses for whole-panel collapse tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display_panel_refresh import PanelRefreshMixin
from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.actions.agents._panel_navigation import AgentPanelNavigationMixin
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.models.fold_state import FoldStateManager


class AgentPanelCollapseApp(
    EntryJumpAgentHistoryMixin,
    AgentPanelDetailMixin,
    AgentFoldingMixin,
    AgentSelectionMixin,
    AgentPanelNavigationMixin,
    AgentNavigationOrderMixin,
    PanelRefreshMixin,
):
    """Minimal application harness for panel collapse behavior."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        focused_key: str | None = None,
        merged: bool = False,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 7
        self._agents = agents
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = merged
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key,
            merge_tribe_panels=merged,
        )
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_keys: set[str | None] = set()
        self._panel_isolation_revert = None
        self._expanded_panel_focus = False
        self._panel_selection_memory: dict[
            str | None, tuple[str, int | tuple[str, ...]]
        ] = {}
        self._current_group_key: tuple[str, ...] | None = None
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_index_cache: tuple[Any, bool, Any] | None = None
        self.refresh_calls: list[bool] = []
        self.refilter_kwargs: list[dict[str, object]] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []
        self.group_fold_changes: list[tuple[str | None, tuple[str, ...], bool]] = []
        self.affected_refreshes: list[set[str | None]] = []
        self.footer_refresh_calls = 0
        self.notifications: list[str] = []
        self._entry_jump_agents_anchor_stack = []
        self._entry_jump_agents_forward_anchor_stack = []
        self.armed_departures: list[Agent] = []

    def _agent_panel_index(self) -> Any:
        cached = self._panel_index_cache
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == self._agent_panels_grouped
        ):
            return cached[2]
        index = build_agent_panel_index(
            self._agents,
            dismissable_statuses=(),
            merge_tribe_panels=self._agent_panels_grouped,
        )
        self._panel_index_cache = (
            self._agents,
            self._agent_panels_grouped,
            index,
        )
        return index

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tribe_panels=self._agent_panels_grouped,
        )

    def _invalidate_agent_panel_cache(self) -> None:
        self._nav_stops_cache = None
        self._panel_index_cache = None

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)
        if list_changed:
            self._sync_panel_group()

    def _refilter_agents(
        self,
        *,
        refresh_content_index: bool = True,
    ) -> None:
        self.refilter_kwargs.append({"refresh_content_index": refresh_content_index})

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        del old_focused_idx
        self._refresh_agents_display(list_changed=False)

    def _refresh_affected_panel_widgets(self, affected_keys: set[str | None]) -> bool:
        self.affected_refreshes.append(set(affected_keys))
        return True

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        return False

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        if agent is not None:
            self.armed_departures.append(agent)

    def _record_agents_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))

    def _record_agents_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: str | None = None,
    ) -> None:
        self.group_fold_changes.append((panel_key, group_key, collapsed))


def make_agent(*, name: str, project: str, tribe: str | None) -> Agent:
    """Create a running agent for panel collapse tests."""

    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file=f"/r/{project}/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 15, 12, 0, 0),
        raw_suffix=name,
        agent_name=name,
        tribe=tribe,
    )


def make_multi_panel_agents() -> list[Agent]:
    """Create agents spanning the default, alpha, and beta panels."""

    return [
        make_agent(name="no_tribe", project="home", tribe=None),
        make_agent(name="raw-first", project="zeta", tribe="alpha"),
        make_agent(name="render-first", project="alpha", tribe="alpha"),
        make_agent(name="beta", project="beta", tribe="beta"),
    ]


def make_four_panel_agents() -> list[Agent]:
    """Create agents spanning four panels."""

    return [
        *make_multi_panel_agents(),
        make_agent(name="gamma", project="gamma", tribe="gamma"),
    ]
