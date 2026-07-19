"""Shared harness for agent neighbor navigation tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldStateManager


class _Debouncer:
    def __init__(self) -> None:
        self.scheduled = 0

    def schedule(self, _callback: Any) -> None:
        self.scheduled += 1


class NeighborApp(TreeNavigationMixin, AdvancedNavigationMixin, AgentDisplayMixin):
    """Small harness for the shared ``~`` action and Agents neighbor helpers."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        focused_key: str | None = None,
        collapsed: list[tuple[str, ...]] | None = None,
        collapsed_panel_keys: set[str | None] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.changespecs = []
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 7
        self._agents_with_children = list(agents)
        self._agents = list(agents)
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_panels_grouped = False
        self._collapsed_panel_keys = set(collapsed_panel_keys or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key: tuple[str, ...] | None = None
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self._agent_neighbor_index_cache = None
        self._dismiss_revive_epoch = 0
        self._agent_info_metrics_cache = None
        self._dismissed_agents = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_changespec_banner: dict[str, tuple[str, ...]] = {}
        self._entry_jump_changespec_banner_to_hint: dict[tuple[str, ...], str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._marked_agents = set()
        self._unread_completed_agent_ids = set()
        self._manual_unread_agent_ids = set()
        self._fold_counts = {}
        self._agent_search_query = ""
        self._countdown_remaining = 0
        self.refresh_interval = 10
        self.artifact_file_viewer_guard_active = False
        self.notify = MagicMock()
        self.armed_departures: list[Agent] = []
        self.acknowledged: list[Agent] = []
        self.highlight_refreshes = 0
        self.focused_panel_refreshes: list[int | None] = []
        self.info_updates = 0
        self.detail_updates = 0
        self.display_refreshes: list[dict[str, Any]] = []
        self.current_tab_refreshes = 0
        self.jump_footer_updates = 0
        self.revived_agents: list[Agent] = []
        self.refilter_calls = 0
        self.group_fold_changes: list[tuple[tuple[str, ...], bool]] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []
        self._agent_detail_debouncer = _Debouncer()
        self.pushed_screens: list[Any] = []
        self.pushed_callbacks: list[Any] = []

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        if agent is not None:
            self.armed_departures.append(agent)

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        self.acknowledged.append(agent)
        return True

    def _refresh_panel_highlights(self) -> None:
        self.highlight_refreshes += 1

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.display_refreshes.append(kwargs)
        if kwargs.get("list_changed"):
            self._sync_panel_group()

    def _refresh_current_tab(self) -> None:
        self.current_tab_refreshes += 1

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        self.focused_panel_refreshes.append(old_focused_idx)

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_detail_immediate(self) -> None:
        self.detail_updates += 1

    def _fire_debounced_detail_update(self) -> None:
        return

    def _do_revive_agent(self, agent: Agent) -> None:
        self.revived_agents.append(agent)

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self.refilter_calls += 1
        focused_key = self._panel_group.focused_key
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents_with_children,
            self._fold_manager,
        )
        self._invalidate_agent_panel_cache()
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )

    def _expand_agent_panel(self, panel_key: str | None) -> bool:
        if panel_key not in self._collapsed_panel_keys:
            return False
        self._collapsed_panel_keys.remove(panel_key)
        self._invalidate_agent_panel_cache()
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _persist_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: str | None = None,
    ) -> None:
        del panel_key
        self.group_fold_changes.append((group_key, collapsed))

    def _persist_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed_screens.append(screen)
        self.pushed_callbacks.append(callback)


def make_agent(
    name: str,
    *,
    tag: str | None = None,
    status: str = "RUNNING",
    cl: str = "demo",
    project: str = "proj",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 5, 23, 12, 0, 0),
        raw_suffix=name,
        agent_name=name,
        tag=tag,
    )
