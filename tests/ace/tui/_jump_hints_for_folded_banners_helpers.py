"""Shared fixtures for folded-banner jump-hint tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._unread import AgentUnreadMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _StubApp(AgentUnreadMixin, AdvancedNavigationMixin):
    """Minimal harness for the agents-tab jump-mode helpers."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        collapsed: list[tuple[str, ...]] | None = None,
        collapsed_by_panel: dict[str | None, list[tuple[str, ...]]] | None = None,
        collapsed_panels: set[str | None] | None = None,
        patch_result: bool = True,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 7
        self._agents = agents
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        for panel_key, keys in (collapsed_by_panel or {}).items():
            self._group_fold_registry.for_panel(panel_key).collapse_keys(keys)
        self._collapsed_panel_keys = set(collapsed_panels or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._current_group_key: tuple[str, ...] | None = None
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_panel: dict[str, Any] = {}
        self._entry_jump_panel_to_hint: dict[Any, str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[Any]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_info_metrics_cache: tuple[Any, ...] | None = None
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.notification_count_refresh_calls = 0
        self.artifact_file_viewer_guard_active = False
        self.jump_footer_updates = 0
        self.notify = MagicMock()

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _panel_keys_per_agent(self) -> list:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[str | None], focused_key: str | None
    ) -> None:
        for index, panel_key in enumerate(keys_per_agent):
            if panel_key == focused_key:
                self.current_idx = index
                return
        self.current_idx = 0

    # The mixin would normally drive a full refresh; tests don't render, but
    # unread assertions need to know whether refresh fallback was requested.
    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_current_tab(self) -> None:
        return

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


def _agent(
    *,
    project: str,
    cl: str,
    name: str,
    tag: str | None = None,
    status: str = "RUNNING",
    raw_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=raw_suffix,
    )
