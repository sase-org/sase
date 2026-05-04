"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from .base import OptionListNavigationMixin

# Reuse the same type→color mapping from the agent list widget
_TYPE_COLORS: dict[AgentType, str] = {
    AgentType.RUNNING: "#87AFFF",
    AgentType.WORKFLOW: "#FF87D7",
}

# Per-step-type colors for workflow child entries
_STEP_TYPE_COLORS: dict[str, str] = {
    "agent": "#5FD7FF",  # Bright cyan — LLM agent steps stand out
    "bash": "#FFAF5F",  # Warm amber — shell commands
    "python": "#87D787",  # Soft green — code execution
    "parallel": "#D7AFFF",  # Soft lavender — parallel orchestration
}

_STATUS_COLORS: dict[str, str] = {
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    "WAITING INPUT": "#FF87D7",
}


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


class DismissedAgentSelectModal(
    OptionListNavigationMixin, ModalScreen[list[Agent] | None]
):
    """Modal for selecting dismissed agents to revive (supports multi-select)."""

    _option_list_id = "dismissed-agent-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("tab", "toggle_mark", "Mark", priority=True),
        Binding("ctrl+a", "toggle_all", "Mark All", priority=True),
    ]

    def __init__(
        self,
        agents: list[Agent],
        *,
        all_dismissed: list[Agent] | None = None,
        loading_archive: bool = False,
    ) -> None:
        """Initialize the modal.

        Args:
            agents: Pre-filtered list of dismissed agents to display
                (parent entries only).
            all_dismissed: All dismissed agents in scope (including children),
                used for computing step counts on workflow parents.
        """
        super().__init__()
        self.agents = agents
        self._all_dismissed = all_dismissed or agents
        self._chat_contents: dict[int, str] = {}
        self._filtered: list[tuple[int, Agent]] = list(enumerate(agents))
        self._step_counts: dict[str, int] = self._compute_step_counts()
        self._marked: set[int] = set()
        self._loading_archive = loading_archive

    def _compute_step_counts(self) -> dict[str, int]:
        """Count child steps per parent (keyed by raw_suffix)."""
        counts: dict[str, int] = {}
        for agent in self._all_dismissed:
            if agent.is_workflow_child and agent.parent_timestamp:
                counts[agent.parent_timestamp] = (
                    counts.get(agent.parent_timestamp, 0) + 1
                )
        return counts

    def _get_child_steps(self, agent: Agent) -> list[Agent]:
        """Get child steps for a parent workflow agent, sorted by step_index."""
        if not agent.raw_suffix:
            return []
        children = [
            a
            for a in self._all_dismissed
            if a.is_workflow_child and a.parent_timestamp == agent.raw_suffix
        ]
        children.sort(key=lambda a: a.step_index if a.step_index is not None else 0)
        return children

    def on_mount(self) -> None:
        """Focus the filter input and pre-load chat contents."""
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
        filter_input.focus()
        if self._filtered:
            self._update_preview(self._filtered[0][1])

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="dismissed-agent-modal-container"):
            yield Label("Revive Agents", id="modal-title")
            yield _ReviveFilterInput(
                placeholder="Type to filter...", id="dismissed-filter"
            )
            with Horizontal(id="dismissed-agent-panels"):
                with Vertical(id="dismissed-agent-list-panel"):
                    yield OptionList(
                        *self._create_options_or_placeholder(),
                        id="dismissed-agent-list",
                    )
                with Vertical(id="dismissed-agent-preview-panel"):
                    with VerticalScroll(id="dismissed-preview-scroll"):
                        yield Static("", id="dismissed-preview-metadata")
                        yield Static("", id="dismissed-preview-content")
            yield Static(
                self._hints_text(),
                id="dismissed-agent-hints",
            )

    def set_agents(
        self,
        agents: list[Agent],
        *,
        all_dismissed: list[Agent] | None = None,
        loading_archive: bool = False,
    ) -> None:
        """Replace modal contents after an on-demand archive load."""
        self.agents = agents
        self._all_dismissed = all_dismissed or agents
        self._step_counts = self._compute_step_counts()
        self._marked = {idx for idx in self._marked if idx < len(self.agents)}
        self._loading_archive = loading_archive

        self._chat_contents.clear()
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        try:
            filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
            self._filtered = self._get_filtered_agents(filter_input.value)
        except Exception:
            self._filtered = list(enumerate(self.agents))

        self._rebuild_options()
        if self._filtered:
            self._update_preview(self._filtered[0][1])
        else:
            self._clear_preview()
        self._update_hints()

    def _get_type_color(self, agent: Agent) -> str:
        """Get the color for an agent's type label."""
        if agent.appears_as_agent:
            return _TYPE_COLORS[AgentType.RUNNING]
        if agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
            return _STEP_TYPE_COLORS[agent.step_type]
        return _TYPE_COLORS.get(agent.agent_type, "#FFFFFF")

    def _get_status_style(self, status: str) -> str:
        """Get Rich style string for a status value."""
        color = _STATUS_COLORS.get(status)
        if color:
            return f"bold {color}"
        return "dim"

    def _format_agent_label(self, agent: Agent, orig_idx: int = -1) -> Text:
        """Create styled text for an agent option."""
        text = Text()

        # Mark indicator
        if orig_idx in self._marked:
            text.append(" \u25cf ", style="bold #00D7D7")
        else:
            text.append("   ")

        # Status icon
        if agent.status == "DONE":
            text.append("\u2714 ", style="bold #5FD75F")
        elif agent.status == "FAILED":
            text.append("\u2718 ", style="bold #FF5F5F")
        else:
            text.append("\u25cb ", style="dim")

        # [type] colored by type
        type_color = self._get_type_color(agent)
        text.append(f"[{agent.display_type}]", style=f"bold {type_color}")
        text.append(" ")

        # Display name
        text.append(agent.display_name, style="bold")

        # Agent name
        if agent.agent_name:
            text.append("  ")
            text.append(f"@{agent.agent_name}", style="#87D7FF")

        # Start time
        text.append("  ")
        text.append(agent.start_time_compact, style="dim")

        # Model
        if agent.model:
            text.append("  ")
            text.append(agent.model, style="dim italic")

        # Step count for workflow parents
        if agent.raw_suffix and agent.raw_suffix in self._step_counts:
            count = self._step_counts[agent.raw_suffix]
            text.append("  ")
            text.append(f"({count} steps)", style="dim #00D7D7")

        return text

    def _create_options(self, agents: list[Agent]) -> list[Option]:
        """Create options from agents."""
        return [
            Option(self._format_agent_label(agent, i), id=str(i))
            for i, agent in enumerate(agents)
        ]

    def _create_options_or_placeholder(self) -> list[Option]:
        """Create agent options or a disabled loading/empty placeholder."""
        if self.agents:
            return self._create_options(self.agents)
        if self._loading_archive:
            return [
                Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
            ]
        return [
            Option(
                Text("No dismissed agents in this scope", style="dim"), disabled=True
            )
        ]

    def _get_filtered_agents(self, filter_text: str) -> list[tuple[int, Agent]]:
        """Get agents matching the filter text."""
        if not filter_text:
            return list(enumerate(self.agents))
        filter_lower = filter_text.lower()
        results: list[tuple[int, Agent]] = []
        for i, agent in enumerate(self.agents):
            label = f"[{agent.display_type}] {agent.display_name}"
            if agent.agent_name:
                label += f" @{agent.agent_name}"
            if filter_lower in label.lower():
                results.append((i, agent))
                continue
            if i in self._chat_contents and filter_lower in self._chat_contents[i]:
                results.append((i, agent))
        return results

    # --- Mark / bulk selection ---

    def action_toggle_mark(self) -> None:
        """Toggle mark on highlighted agent and advance cursor."""
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or highlighted >= len(self._filtered):
            return
        orig_idx = self._filtered[highlighted][0]
        if orig_idx in self._marked:
            self._marked.discard(orig_idx)
        else:
            self._marked.add(orig_idx)
        self._rebuild_options()
        self._update_hints()
        # Auto-advance to next item
        option_list.action_cursor_down()

    def action_toggle_all(self) -> None:
        """Toggle marks on all currently filtered agents."""
        filtered_indices = {idx for idx, _ in self._filtered}
        if filtered_indices and filtered_indices <= self._marked:
            # All filtered items are already marked → unmark them
            self._marked -= filtered_indices
        else:
            # Some or none marked → mark all filtered
            self._marked |= filtered_indices
        self._rebuild_options()
        self._update_hints()

    def _rebuild_options(self) -> None:
        """Rebuild the option list to reflect mark state changes."""
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        old_highlighted = option_list.highlighted
        option_list.clear_options()
        if self._filtered:
            for orig_idx, agent in self._filtered:
                option_list.add_option(
                    Option(self._format_agent_label(agent, orig_idx), id=str(orig_idx))
                )
        elif self._loading_archive:
            option_list.add_option(
                Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
            )
        else:
            option_list.add_option(
                Option(
                    Text("No dismissed agents in this scope", style="dim"),
                    disabled=True,
                )
            )
        if old_highlighted is not None and 0 <= old_highlighted < len(self._filtered):
            option_list.highlighted = old_highlighted

    def _hints_text(self) -> str:
        count = len(self._marked)
        loading = " | archive loading" if self._loading_archive else ""
        if count:
            return (
                "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
                f" | Enter: revive ({count}) | Esc/q: cancel{loading}"
            )
        return (
            "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
            f" | Enter: revive | Esc/q: cancel{loading}"
        )

    def _update_hints(self) -> None:
        """Update the hints bar to reflect current mark count."""
        hints = self.query_one("#dismissed-agent-hints", Static)
        hints.update(self._hints_text())

    def _get_marked_agents(self) -> list[Agent]:
        """Get all marked agents in original order."""
        return [self.agents[i] for i in sorted(self._marked) if i < len(self.agents)]

    # --- Event handlers ---

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        self._filtered = self._get_filtered_agents(event.value)
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        option_list.clear_options()
        if self._filtered:
            for orig_idx, agent in self._filtered:
                option_list.add_option(
                    Option(self._format_agent_label(agent, orig_idx), id=str(orig_idx))
                )
        elif self._loading_archive:
            option_list.add_option(
                Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
            )
        else:
            option_list.add_option(
                Option(
                    Text("No dismissed agents in this scope", style="dim"),
                    disabled=True,
                )
            )
        if self._filtered:
            self._update_preview(self._filtered[0][1])
        else:
            self._clear_preview()
        self._update_hints()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in filter input."""
        # If agents are marked, revive all marked
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        # Otherwise, single selection from filtered list
        filtered = self._get_filtered_agents(event.value.strip())
        if not filtered:
            self.dismiss(None)
            return
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(filtered):
            self.dismiss([filtered[highlighted][1]])
        else:
            self.dismiss([filtered[0][1]])

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
        # If agents are marked, revive all marked
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        # Otherwise, single selection
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self.agents):
                self.dismiss([self.agents[idx]])

    # --- Preview ---

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
        """Update preview panel with structured agent metadata and response."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)

            meta = Text()

            # Header line with decorative separator
            type_color = self._get_type_color(agent)
            header = f"[{agent.display_type}] {agent.display_name}"
            meta.append("\u2501\u2501\u2501 ", style="dim")
            meta.append(header, style=f"bold {type_color}")
            meta.append(
                " " + "\u2501" * max(1, 36 - len(header)),
                style="dim",
            )
            meta.append("\n\n")

            # Structured metadata with aligned labels
            label_width = 12

            meta.append(f"  {'Status':<{label_width}}", style="bold")
            meta.append(agent.status, style=self._get_status_style(agent.status))
            meta.append("\n")

            meta.append(f"  {'Started':<{label_width}}", style="bold")
            meta.append(f"{agent.start_time_display}\n", style="dim")

            meta.append(f"  {'Duration':<{label_width}}", style="bold")
            meta.append(f"{agent.duration_display}\n", style="dim")

            if agent.model:
                meta.append(f"  {'Model':<{label_width}}", style="bold")
                meta.append(f"{agent.model}\n", style="dim italic")

            if agent.llm_provider:
                meta.append(f"  {'Provider':<{label_width}}", style="bold")
                meta.append(f"{agent.llm_provider}\n", style="dim")

            if agent.agent_name:
                meta.append(f"  {'Agent':<{label_width}}", style="bold")
                meta.append(f"@{agent.agent_name}\n", style="#87D7FF")

            if agent.workflow and not agent.appears_as_agent:
                meta.append(f"  {'Workflow':<{label_width}}", style="bold")
                meta.append(f"{agent.workflow}\n", style="dim")

            # Child step summary
            children = self._get_child_steps(agent)
            if children:
                meta.append(f"\n  \u2500\u2500 Steps ({len(children)}) ")
                meta.append(
                    "\u2500" * 24 + "\n",
                    style="dim",
                )
                for i, child in enumerate(children, 1):
                    step_type = child.step_type or "step"
                    step_name = child.step_name or child.cl_name
                    status_style = self._get_status_style(child.status)
                    meta.append(f"  {i}. ", style="dim #AAAAAA")
                    step_color = _STEP_TYPE_COLORS.get(step_type, type_color)
                    meta.append(f"[{step_type}] ", style=f"dim {step_color}")
                    meta.append(f"{step_name:<20}", style="dim")
                    meta.append(f"{child.status}\n", style=status_style)

            # Error details
            if agent.error_message:
                meta.append("\n  \u2500\u2500 Error ")
                meta.append("\u2500" * 28 + "\n", style="dim")
                meta.append(f"  {agent.error_message}\n", style="bold #FF5F5F")
                if agent.error_traceback:
                    meta.append(f"  {agent.error_traceback}\n", style="dim #FF5F5F")

            metadata_widget.update(meta)

            # Response content
            raw = agent.get_response_content()
            content = raw.strip() if raw else None

            if content:
                preview = Text()
                preview.append(
                    "\n  \u2500\u2500 Response " + "\u2500" * 26 + "\n",
                    style="dim",
                )
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
