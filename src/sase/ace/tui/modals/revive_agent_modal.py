"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent
from .base import OptionListNavigationMixin
from .revive_agent_rendering import (
    build_metadata_preview,
    build_response_preview,
    create_options,
    format_agent_label,
    get_status_style,
    get_type_color,
    placeholder_option,
)


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
        """Initialize the modal."""
        super().__init__()
        self.agents = agents
        self._all_dismissed = all_dismissed or agents
        self._chat_contents: dict[int, str] = {}
        self._filtered: list[tuple[int, Agent]] = list(enumerate(agents))
        self._step_counts: dict[str, int] = self._compute_step_counts()
        self._marked: set[int] = set()
        self._loading_archive = loading_archive

    def _compute_step_counts(self) -> dict[str, int]:
        """Count child steps per parent, keyed by raw suffix."""
        counts: dict[str, int] = {}
        for agent in self._all_dismissed:
            if agent.is_workflow_child and agent.parent_timestamp:
                counts[agent.parent_timestamp] = (
                    counts.get(agent.parent_timestamp, 0) + 1
                )
        return counts

    def _get_child_steps(self, agent: Agent) -> list[Agent]:
        """Get child steps for a parent workflow agent, sorted by step index."""
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
        """Replace modal contents after an on-demand bundle load."""
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
        return get_type_color(agent)

    def _get_status_style(self, status: str) -> str:
        """Get Rich style string for a status value."""
        return get_status_style(status)

    def _format_agent_label(self, agent: Agent, orig_idx: int = -1) -> Text:
        """Create styled text for an agent option."""
        return format_agent_label(
            agent,
            orig_idx,
            marked=self._marked,
            step_counts=self._step_counts,
        )

    def _create_options(self, agents: list[Agent]) -> list[Option]:
        """Create options from agents."""
        return create_options(
            agents,
            marked=self._marked,
            step_counts=self._step_counts,
        )

    def _create_options_or_placeholder(self) -> list[Option]:
        """Create agent options or a disabled loading/empty placeholder."""
        if self.agents:
            return self._create_options(self.agents)
        return [placeholder_option(loading_archive=self._loading_archive)]

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
        option_list.action_cursor_down()

    def action_toggle_all(self) -> None:
        """Toggle marks on all currently filtered agents."""
        filtered_indices = {idx for idx, _ in self._filtered}
        if filtered_indices and filtered_indices <= self._marked:
            self._marked -= filtered_indices
        else:
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
            option_list.add_option(placeholder_option(loading_archive=True))
        else:
            option_list.add_option(placeholder_option(loading_archive=False))
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
            option_list.add_option(placeholder_option(loading_archive=True))
        else:
            option_list.add_option(placeholder_option(loading_archive=False))
        if self._filtered:
            self._update_preview(self._filtered[0][1])
        else:
            self._clear_preview()
        self._update_hints()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in filter input."""
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
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
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self.agents):
                self.dismiss([self.agents[idx]])

    def scroll_preview_down(self) -> None:
        """Scroll preview panel down half a page."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        """Scroll preview panel up half a page."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def _update_preview(self, agent: Agent) -> None:
        """Update preview panel with structured agent metadata and response."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)

            metadata_widget.update(
                build_metadata_preview(agent, self._get_child_steps(agent))
            )
            content_widget.update(build_response_preview(agent))

        except Exception:
            pass

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            self.query_one("#dismissed-preview-metadata", Static).update("")
            self.query_one("#dismissed-preview-content", Static).update("")
        except Exception:
            pass
