"""Notification modal for viewing unread agent completions."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from .base import OptionListNavigationMixin


class NotificationModal(
    OptionListNavigationMixin, ModalScreen[tuple[AgentType, str, str | None] | None]
):
    """Modal for viewing and selecting unread agent completion notifications."""

    _option_list_id = "notification-list"
    BINDINGS = [*OptionListNavigationMixin.NAVIGATION_BINDINGS]

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize the notification modal.

        Args:
            agents: List of unread completed agents to display.
        """
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="notification-container"):
            yield Label("Notifications", id="notification-title")
            if self._agents:
                yield OptionList(
                    *self._create_options(),
                    id="notification-list",
                )
            else:
                yield Static(
                    "No unread notifications",
                    id="notification-empty",
                )
            yield Label(
                "Enter: select  q/Esc: close",
                id="notification-hints",
            )

    def _create_styled_label(self, agent: Agent) -> Text:
        """Create styled text for an agent notification option."""
        text = Text()

        # Status indicator with color
        if agent.status == "DONE":
            text.append("DONE", style="bold #00FF00")
        else:
            text.append(agent.status, style="bold #FF5F5F")

        text.append("  ", style="")

        # Agent display type and CL name
        text.append(f"[{agent.display_type}]", style="bold")
        text.append(f" {agent.cl_name}", style="")

        # Duration
        text.append(f"  ({agent.duration_display})", style="dim")

        return text

    def _create_options(self) -> list[Option]:
        """Create options from agents."""
        return [
            Option(self._create_styled_label(agent), id=str(i))
            for i, agent in enumerate(self._agents)
        ]

    def on_mount(self) -> None:
        """Focus the option list on mount."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
            option_list.focus()
        except Exception:
            pass  # No list if empty

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._agents):
                self.dismiss(self._agents[idx].identity)
