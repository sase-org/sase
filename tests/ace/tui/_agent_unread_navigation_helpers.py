"""Shared helpers for unread agent navigation tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.actions.agents._unread import AgentUnreadMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent


class UnreadJumpApp(AgentsMixinCore, BasicNavigationMixin, AdvancedNavigationMixin):
    def __init__(
        self,
        agents: list[Agent],
        *,
        visible: list[int] | None = None,
        stops: list[tuple[str, int | tuple[str, ...]]] | None = None,
        current_idx: int = 0,
        patch_result: bool = True,
        with_panels: bool = False,
        focused_key: str | None = None,
        merge_tag_panels: bool = False,
        collapsed_panels: set[str | None] | None = None,
    ) -> None:
        self._agents = agents
        self.current_tab = "agents"
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 3
        self._current_group_key: tuple[str, ...] | None = None
        self._agent_panels_grouped = merge_tag_panels
        self._collapsed_panel_keys = set(collapsed_panels or ())
        if with_panels:
            self._panel_group = AgentPanelGroup.from_agents(
                agents,
                focused_key,
                merge_tag_panels=merge_tag_panels,
                collapsed_panel_keys=self._collapsed_panel_keys,
            )
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._visible = visible
        self._stops = stops
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.debounced_refresh_calls = 0
        self.notification_count_refresh_calls = 0

    def _agents_visible_order(self) -> list[int]:
        if self._visible is not None:
            return self._visible
        return list(range(len(self._agents)))

    def _panel_navigation_stops(self) -> list[tuple[str, int | tuple[str, ...]]]:
        if self._stops is not None:
            return self._stops
        return [("agent", idx) for idx in self._agents_visible_order()]

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        if kwargs.get("list_changed") and hasattr(self, "_panel_group"):
            self._sync_panel_group()
        self.refresh_calls.append(kwargs)

    def _refresh_agents_display_debounced(self) -> None:
        self.debounced_refresh_calls += 1

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


class LeaderUnreadJumpApp(
    LeaderModeMixin,
    AgentFoldingMixin,
    AgentUnreadMixin,
    AgentNavigationOrderMixin,
    AdvancedNavigationMixin,
):
    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        collapsed_panels: set[str | None] | None = None,
    ) -> None:
        self._agents = agents
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 3
        self.current_tab = "agents"
        self._current_group_key: tuple[str, ...] | None = None
        self._agent_panels_grouped = False
        self._collapsed_panel_keys = set(collapsed_panels or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key=None,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._leader_mode_active = True
        self._last_leader_key: str | None = None
        self._keymap_registry = load_keymap_registry({})
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.current_tab_refresh_calls = 0
        self.notification_count_refresh_calls = 0
        self.notifications: list[str] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)

    def _refresh_current_tab(self) -> None:
        self.current_tab_refresh_calls += 1

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(self._agents, merge_tag_panels=False)

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        if kwargs.get("list_changed"):
            focused_key = self._panel_group.focused_key
            self._panel_group = AgentPanelGroup.from_agents(
                self._agents,
                focused_key,
                collapsed_panel_keys=self._collapsed_panel_keys,
            )
        self.refresh_calls.append(kwargs)

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1

    def _invalidate_agent_panel_cache(self) -> None:
        self._nav_stops_cache = None

    def _record_agents_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))
