"""Pinned agent list panel widget for the ace TUI."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from ..models.agent import Agent, AgentType
from .agent_list import (
    _AGENT_TYPE_COLORS,
    _DONE_ICON,
    _HIDDEN_ICON,
    _STEP_TYPE_COLORS,
)


class PinnedAgentList(Static):
    """Dedicated panel showing pinned agents below the agent detail area."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agents: list[Agent] = []
        self._selected_idx: int = 0

    @property
    def selected_idx(self) -> int:
        return self._selected_idx

    @property
    def agents(self) -> list[Agent]:
        return self._agents

    def update_agents(self, agents: list[Agent], focused: bool = False) -> None:
        """Update the pinned agent list and re-render.

        Args:
            agents: List of pinned Agent objects.
            focused: Whether the pinned panel currently has logical focus.
        """
        self._agents = agents
        if not agents:
            self._selected_idx = 0
            self.display = False
            return

        self.display = True
        # Clamp selected index
        if self._selected_idx >= len(agents):
            self._selected_idx = len(agents) - 1

        self._refresh_content(focused)

    def select_next(self) -> Agent | None:
        """Move selection to the next pinned agent. Returns the newly selected agent."""
        if not self._agents:
            return None
        if self._selected_idx < len(self._agents) - 1:
            self._selected_idx += 1
        else:
            self._selected_idx = 0
        return self._agents[self._selected_idx]

    def select_prev(self) -> Agent | None:
        """Move selection to the previous pinned agent. Returns the newly selected agent."""
        if not self._agents:
            return None
        if self._selected_idx > 0:
            self._selected_idx -= 1
        else:
            self._selected_idx = len(self._agents) - 1
        return self._agents[self._selected_idx]

    def get_selected_agent(self) -> Agent | None:
        """Get the currently selected pinned agent."""
        if self._agents and 0 <= self._selected_idx < len(self._agents):
            return self._agents[self._selected_idx]
        return None

    def set_focused(self, focused: bool) -> None:
        """Update the visual focus state."""
        if focused:
            self.add_class("focused")
        else:
            self.remove_class("focused")
        if self._agents:
            self._refresh_content(focused)

    def _refresh_content(self, focused: bool = False) -> None:
        """Re-render the pinned agents list."""
        text = Text()
        self.border_title = f"\U0001f4cc Pinned ({len(self._agents)})"

        for i, agent in enumerate(self._agents):
            if i > 0:
                text.append("\n")

            is_selected = focused and i == self._selected_idx

            # Selection indicator
            if is_selected:
                text.append("\u25b8 ", style="bold #FFD700")
            else:
                text.append("  ")

            # Done icon
            text.append(f"{_DONE_ICON} ", style="bold red")

            # Hidden icon for agents that are normally hidden
            if agent.hidden:
                text.append(f"{_HIDDEN_ICON} ", style="bold #FF5F87")

            # Agent type indicator
            dt = agent.get_display_type()
            if agent.appears_as_agent:
                color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
            elif agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
                color = _STEP_TYPE_COLORS[agent.step_type]
            else:
                color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")
            text.append(f"[{dt}] ", style=f"bold {color}")

            # Agent display name
            name_style = "bold #00D7AF" if is_selected else "#00D7AF"
            text.append(agent.display_name, style=name_style)

            # Status
            text.append(" (", style="dim")
            if agent.status in ("DONE", "PLAN DONE"):
                text.append(agent.status, style="bold #5FD75F")
            elif agent.status == "FAILED":
                text.append(agent.status, style="bold #FF5F5F")
            elif agent.status == "PLAN COMMITTED":
                text.append(agent.status, style="bold #00D7AF")
            else:
                text.append(agent.status, style="dim")
            text.append(")", style="dim")

            # Agent name annotation
            if agent.agent_name:
                text.append(f" @{agent.agent_name}", style="#FFD700")

        self.update(text)
