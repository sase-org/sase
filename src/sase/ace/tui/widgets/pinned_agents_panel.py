"""Pinned agents panel widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from .agent_list import (
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _DISMISSIBLE_STATUSES,
    _DONE_ICON,
    _PIN_ICON,
)


class PinnedAgentsPanel(OptionList):
    """Bottom panel showing pinned agents in the agent detail area."""

    class SelectionChanged(Message):
        """Message sent when selection changes."""

        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the pinned agents panel."""
        super().__init__(**kwargs)
        self._agents: list[Agent] = []
        self._programmatic_update: bool = False

    def update_list(
        self,
        agents: list[Agent],
        current_idx: int,
        focused: bool = False,
    ) -> None:
        """Update the list with pinned agents.

        Args:
            agents: List of pinned agents to display.
            current_idx: Index of currently selected pinned agent.
            focused: Whether this panel currently has focus.
        """
        self._programmatic_update = True
        self._agents = agents
        self.clear_options()

        for i, agent in enumerate(agents):
            option = _format_pinned_option(agent, i, is_selected=(i == current_idx))
            self.add_option(option)

        if agents and 0 <= current_idx < len(agents):
            self.highlighted = current_idx

        # Update border title with count
        self.border_title = f"\U0001f4cc Pinned ({len(agents)})"

        # Update focus styling
        if focused:
            self.add_class("focused-panel")
        else:
            self.remove_class("focused-panel")

        self.call_later(self._clear_programmatic_flag)

    def update_highlight(self, idx: int) -> None:
        """Move the highlight without rebuilding options.

        Args:
            idx: Index to highlight.
        """
        if self._agents and 0 <= idx < len(self._agents):
            self._programmatic_update = True
            self.highlighted = idx
            self.call_later(self._clear_programmatic_flag)

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Handle option highlight (keyboard navigation)."""
        if event.option_index is not None and not self._programmatic_update:
            self.post_message(self.SelectionChanged(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if event.option_index is not None:
            self.post_message(self.SelectionChanged(event.option_index))


def _format_pinned_option(
    agent: Agent,
    index: int,
    is_selected: bool,
) -> Option:
    """Format a pinned agent as an option for display.

    Args:
        agent: The Agent to format.
        index: Index of the agent in the list.
        is_selected: Whether this is the currently selected item.

    Returns:
        An Option for the OptionList.
    """
    text = Text()

    # Approve icon
    if agent.approve:
        text.append(f"{_APPROVE_ICON} ", style="bold #00FFFF")

    # Pin icon (always shown for pinned agents)
    if agent.status in _DISMISSIBLE_STATUSES:
        text.append(f"{_PIN_ICON} ", style="bold #FFD700")

    # Done icon
    if agent.status in _DISMISSIBLE_STATUSES:
        text.append(f"{_DONE_ICON} ", style="dim red")

    # Agent type indicator with color
    dt = agent.get_display_type()
    if agent.appears_as_agent:
        color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
    else:
        color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")
    text.append(f"[{dt}] ", style=f"bold {color}")

    # Display name
    name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    text.append(agent.display_name, style=name_style)

    # Status
    text.append(" (", style="dim")
    if agent.status in ("DONE", "PLAN DONE", "PLAN COMMITTED"):
        text.append(agent.status, style="bold #5FD75F")
    elif agent.status == "FAILED":
        text.append(agent.status, style="bold #FF5F5F")
    else:
        text.append(agent.status, style="dim")
    text.append(")", style="dim")

    # Agent name
    if agent.agent_name:
        text.append(f" @{agent.agent_name}", style="#FFD700")

    return Option(text, id=f"pinned:{index}:{agent.agent_type.value}:{agent.cl_name}")
