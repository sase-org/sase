"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent
from .base import OptionListNavigationMixin


class _ReviveFilterInput(Input):
    """Custom input for revive modal with scroll key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
    ]

    def action_scroll_preview_down(self) -> None:
        """Scroll the preview panel down."""
        modal = self.screen
        if isinstance(modal, DismissedAgentSelectModal):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        """Scroll preview up, or clear input if already at top."""
        modal = self.screen
        if isinstance(modal, DismissedAgentSelectModal):
            scroll = modal.query_one("#dismissed-preview-scroll", VerticalScroll)
            if scroll.scroll_y > 0:
                modal.scroll_preview_up()
            elif self.cursor_position > 0:
                self.value = self.value[self.cursor_position :]
                self.cursor_position = 0


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
        self._filtered: list[tuple[int, Agent]] = list(enumerate(agents))

    def on_mount(self) -> None:
        """Focus the filter input and pre-load chat contents."""
        # Pre-load chat content for search filtering
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
        filter_input.focus()
        # Show preview for first item
        if self._filtered:
            self._update_preview(self._filtered[0][1])

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="dismissed-agent-modal-container"):
            yield Label("Select Agent to Revive", id="modal-title")
            yield _ReviveFilterInput(
                placeholder="Type to filter...", id="dismissed-filter"
            )
            with Horizontal(id="dismissed-agent-panels"):
                with Vertical(id="dismissed-agent-list-panel"):
                    yield OptionList(
                        *self._create_options(self.agents),
                        id="dismissed-agent-list",
                    )
                with Vertical(id="dismissed-agent-preview-panel"):
                    yield Label("Preview", id="dismissed-preview-label")
                    with VerticalScroll(id="dismissed-preview-scroll"):
                        yield Static("", id="dismissed-preview-metadata")
                        yield Static("", id="dismissed-preview-content")
            yield Static(
                "j/k: navigate | ^d/^u: scroll preview | Enter: select | Esc/q: cancel",
                id="dismissed-agent-hints",
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
        self._filtered = self._get_filtered_agents(event.value)
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        option_list.clear_options()
        for orig_idx, agent in self._filtered:
            option_list.add_option(
                Option(self._format_agent_label(agent), id=str(orig_idx))
            )
        # Update preview for first filtered item
        if self._filtered:
            self._update_preview(self._filtered[0][1])
        else:
            self._clear_preview()

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

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update preview when highlighting changes."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self.agents):
                self._update_preview(self.agents[idx])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self.agents):
                self.dismiss(self.agents[idx])

    def scroll_preview_down(self) -> None:
        """Scroll preview panel down (half page)."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        """Scroll preview panel up (half page)."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def _update_preview(self, agent: Agent) -> None:
        """Update preview panel with agent metadata and response content."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)

            # Build metadata
            meta = Text()
            meta.append(f"[{agent.display_type}]", style="bold #FF87D7")
            meta.append(" ")
            meta.append(agent.cl_name, style="bold")
            if agent.agent_name:
                meta.append(f"  @{agent.agent_name}", style="#87D7FF")
            meta.append("\n")

            meta.append("Status: ", style="bold")
            meta.append(f"{agent.status}\n")

            meta.append("Started: ", style="bold")
            meta.append(f"{agent.start_time_display}\n")

            if agent.workflow:
                meta.append("Workflow: ", style="bold")
                meta.append(f"{agent.workflow}\n")

            if agent.model:
                meta.append("Model: ", style="bold")
                meta.append(f"{agent.model}\n")

            if agent.error_message:
                meta.append("Error: ", style="bold red")
                meta.append(f"{agent.error_message}\n", style="red")

            metadata_widget.update(meta)

            # Show response content preview (always use original casing)
            raw = agent.get_response_content()
            content = raw.strip() if raw else None

            if content:
                # Show separator and content
                preview = Text()
                preview.append("--- Response ---\n", style="dim")
                preview.append(content[:5000])
                if len(content) > 5000:
                    preview.append("\n... (truncated)", style="dim")
                content_widget.update(preview)
            else:
                content_widget.update(Text("(no response content)", style="dim italic"))

        except Exception:
            pass

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            self.query_one("#dismissed-preview-metadata", Static).update("")
            self.query_one("#dismissed-preview-content", Static).update("")
        except Exception:
            pass
