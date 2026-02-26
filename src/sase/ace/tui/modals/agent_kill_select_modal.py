"""Agent kill selection modal for bulk-killing running agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, SelectionList

if TYPE_CHECKING:
    from ..models import Agent


class AgentKillSelectModal(ModalScreen[list[int] | None]):
    """Modal for selecting multiple running agents to kill.

    Returns a list of selected agent indices or None if cancelled.
    """

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("space", "toggle_selection", "Toggle"),
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize the agent kill selection modal.

        Args:
            agents: List of killable agents (must have pid).
        """
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Kill Running Agents", id="modal-title")
            yield Label(
                "Space to toggle, Enter to kill selected, Esc to cancel",
                id="agent-kill-hint",
            )
            yield SelectionList[int](
                *self._build_selections(),
                id="agent-kill-list",
            )

    def _build_selections(self) -> list[tuple[Text, int]]:
        """Build SelectionList items from agents."""
        items: list[tuple[Text, int]] = []
        for i, agent in enumerate(self._agents):
            text = Text()
            text.append(f"[{agent.display_type}]", style="bold #00D7AF")
            text.append(f" {agent.cl_name}", style="")
            # Add extra context
            context_parts: list[str] = []
            if agent.agent_name:
                context_parts.append(agent.agent_name)
            if agent.mentor_profile and agent.mentor_name:
                context_parts.append(f"{agent.mentor_profile}:{agent.mentor_name}")
            elif agent.hook_command:
                context_parts.append(agent.hook_command)
            elif agent.workflow:
                context_parts.append(agent.workflow)
            if context_parts:
                text.append(f" ({', '.join(context_parts)})", style="dim")
            text.append(f" PID {agent.pid}", style="dim italic")
            items.append((text, i))
        return items

    def on_mount(self) -> None:
        """Focus the selection list on mount."""
        sel_list = self.query_one("#agent-kill-list", SelectionList)
        sel_list.focus()

    def action_cursor_down(self) -> None:
        """Move cursor down."""
        self.query_one("#agent-kill-list", SelectionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up."""
        self.query_one("#agent-kill-list", SelectionList).action_cursor_up()

    def action_toggle_selection(self) -> None:
        """Toggle current selection."""
        sel_list = self.query_one("#agent-kill-list", SelectionList)
        sel_list.action_select()

    def action_confirm(self) -> None:
        """Confirm selection and dismiss with selected indices."""
        sel_list = self.query_one("#agent-kill-list", SelectionList)
        selected = list(sel_list.selected)
        if selected:
            self.dismiss(selected)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel and dismiss."""
        self.dismiss(None)
