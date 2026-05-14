"""Shared selected-agent helpers for Agents-tab actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


class AgentSelectionMixin:
    """Mixin providing selected-agent and focused-panel accessors."""

    _agents: list[Agent]
    current_idx: int

    def _get_selected_agent(self) -> Agent | None:
        """Get the currently selected agent, or None if no valid selection."""
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
