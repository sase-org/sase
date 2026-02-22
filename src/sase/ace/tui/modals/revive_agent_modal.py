"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from ..models.agent import Agent
from .base import FilterInput, OptionListNavigationMixin


class DismissedAgentSelectModal(OptionListNavigationMixin, ModalScreen[Agent | None]):
    """Modal for selecting a dismissed agent to revive."""

    _option_list_id = "dismissed-agent-list"
    BINDINGS = [*OptionListNavigationMixin.NAVIGATION_BINDINGS]

    def __init__(self, agents: list[Agent]) -> None:
        """Initialize the modal.

        Args:
            agents: Pre-filtered list of dismissed agents to display.
        """
        super().__init__()
        self.agents = agents
        self._chat_contents: dict[int, str] = {}

    def on_mount(self) -> None:
        """Focus the filter input and pre-load chat contents."""
        # Pre-load chat content for search filtering
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        filter_input = self.query_one("#dismissed-filter", FilterInput)
        filter_input.focus()

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Select Agent to Revive", id="modal-title")
            yield FilterInput(placeholder="Type to filter...", id="dismissed-filter")
            yield OptionList(
                *self._create_options(self.agents),
                id="dismissed-agent-list",
            )

    def _format_agent_label(self, agent: Agent) -> Text:
        """Create styled text for an agent option."""
        text = Text()
        # [type] in colored brackets
        display_type = agent.display_type
        text.append(f"[{display_type}]", style="bold #FF87D7")
        text.append(" ")
        # CL name
        text.append(agent.cl_name, style="bold")
        text.append("  ")
        # Time
        text.append(agent.start_time_short, style="dim")
        # Agent name if set
        if agent.agent_name:
            text.append("  ")
            text.append(f"@{agent.agent_name}", style="#87D7FF")
        # Status
        text.append("  ")
        text.append(agent.status, style="dim italic")
        return text

    def _create_options(self, agents: list[Agent]) -> list[Option]:
        """Create options from agents."""
        return [
            Option(self._format_agent_label(agent), id=str(i))
            for i, agent in enumerate(agents)
        ]

    def _get_filtered_agents(self, filter_text: str) -> list[tuple[int, Agent]]:
        """Get agents matching the filter text.

        Returns list of (original_index, agent) tuples.
        """
        if not filter_text:
            return list(enumerate(self.agents))
        filter_lower = filter_text.lower()
        results: list[tuple[int, Agent]] = []
        for i, agent in enumerate(self.agents):
            # Match against display label
            label = f"[{agent.display_type}] {agent.cl_name}"
            if agent.agent_name:
                label += f" @{agent.agent_name}"
            if filter_lower in label.lower():
                results.append((i, agent))
                continue
            # Match against chat content
            if i in self._chat_contents and filter_lower in self._chat_contents[i]:
                results.append((i, agent))
        return results

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        filtered = self._get_filtered_agents(event.value)
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        option_list.clear_options()
        for orig_idx, agent in filtered:
            option_list.add_option(
                Option(self._format_agent_label(agent), id=str(orig_idx))
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in filter input."""
        filtered = self._get_filtered_agents(event.value.strip())
        if not filtered:
            self.dismiss(None)
            return
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(filtered):
            self.dismiss(filtered[highlighted][1])
        else:
            self.dismiss(filtered[0][1])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self.agents):
                self.dismiss(self.agents[idx])
