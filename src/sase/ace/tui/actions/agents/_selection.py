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
            return self._agents[self.current_idx]
        return None

    def _agents_in_focused_panel(self) -> list[Agent]:
        """Return the agents in the currently focused tag panel.

        Falls back to the full agent list when ``_panel_group`` has not
        been built yet (early lifecycle window before the first refresh).
        """
        from ...models.agent_panels import agents_for_panel

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return list(self._agents)
        return agents_for_panel(
            self._agents,
            panel_group.focused_key,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )
