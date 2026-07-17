"""Shared selected-agent helpers for Agents-tab actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panel_summary import (
        AgentPanelSummarySnapshot,
        CollapsedAgentPanelFocus,
    )


class AgentSelectionMixin:
    """Mixin providing selected-agent and focused-panel accessors."""

    _agents: list[Agent]
    current_idx: int

    def _resolve_focused_collapsed_panel(
        self,
    ) -> CollapsedAgentPanelFocus | None:
        """Resolve whole-panel focus, with ``None`` panel keys kept explicit."""
        if getattr(self, "current_tab", None) != "agents":
            return None
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return None
        panel_keys = getattr(panel_group, "panel_keys", None)
        focused_idx = getattr(panel_group, "focused_idx", -1)
        if panel_keys is None or not (0 <= focused_idx < len(panel_keys)):
            return None
        panel_key = panel_keys[focused_idx]
        if panel_key not in getattr(self, "_collapsed_panel_keys", set()):
            return None

        from ...models.agent_panel_summary import CollapsedAgentPanelFocus

        return CollapsedAgentPanelFocus(panel_key=panel_key)

    def _focused_collapsed_panel_summary(
        self,
    ) -> AgentPanelSummarySnapshot | None:
        """Build the current collapsed-panel presentation from cached rows."""
        focus = self._resolve_focused_collapsed_panel()
        if focus is None:
            return None
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        agents = panel_index.slice_for(focus.panel_key).agents

        from ...models.agent_panel_summary import build_agent_panel_summary_snapshot

        return build_agent_panel_summary_snapshot(
            focus.panel_key,
            agents,
            unread_ids=getattr(self, "_unread_completed_agent_ids", set()),
            marked_ids=getattr(self, "_marked_agents", set()),
        )

    def _get_selected_agent(self) -> Agent | None:
        """Get the currently selected agent, or None if no valid selection."""
        if self._resolve_focused_collapsed_panel() is not None:
            return None
        if self._agents and 0 <= self.current_idx < len(self._agents):
            from ...models.agent_panels import agent_is_rendered_in_agents_panel

            agent = self._agents[self.current_idx]
            if agent_is_rendered_in_agents_panel(agent):
                return agent
        return None

    def _agents_in_focused_panel(self) -> list[Agent]:
        """Return the agents in the currently focused tag panel.

        Falls back to the full agent list when ``_panel_group`` has not
        been built yet (early lifecycle window before the first refresh).
        """
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            from ...models.agent_panels import agent_is_rendered_in_agents_panel

            return [a for a in self._agents if agent_is_rendered_in_agents_panel(a)]
        from ._navigation_order import rendered_panel_slice

        _global_indices, agents = rendered_panel_slice(self, panel_group.focused_key)
        return list(agents)
