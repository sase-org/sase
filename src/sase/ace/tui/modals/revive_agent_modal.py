"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from .base import OptionListNavigationMixin

if TYPE_CHECKING:
    from ...agent_query.archive_planner import ArchiveQueryPage, ArchiveQueryResult

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


class _ArchiveQueryProvider(Protocol):
    """Archive-backed query and hydration hooks used by the revive modal."""

    def search(
        self,
        query: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> ArchiveQueryPage:
        """Return a page of archive summary rows."""
        ...

    def hydrate(self, result: ArchiveQueryResult) -> list[Agent]:
        """Hydrate the selected archive result and related rows."""
        ...


@dataclass
class _DismissedEntry:
    """One selectable revive row, either hydrated or archive-summary backed."""

    agent: Agent | None = None
    archive_result: ArchiveQueryResult | None = None


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
        Binding("ctrl+n", "load_more", "More", priority=True),
    ]

    def __init__(
        self,
        agents: list[Agent],
        *,
        all_dismissed: list[Agent] | None = None,
        loading_archive: bool = False,
        archive_query_provider: _ArchiveQueryProvider | None = None,
        page_size: int = 50,
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
        self._same_session_agents = list(agents)
        self._all_dismissed = all_dismissed or agents
        self._chat_contents: dict[int, str] = {}
        self._entries: list[_DismissedEntry] = [
            _DismissedEntry(agent=agent) for agent in agents
        ]
        self._filtered: list[tuple[int, _DismissedEntry]] = list(
            enumerate(self._entries)
        )
        self._step_counts: dict[str, int] = self._compute_step_counts()
        self._marked: set[int] = set()
        self._loading_archive = loading_archive
        self._archive_query_provider = archive_query_provider
        self._page_size = max(1, page_size)
        self._archive_cursor: int | None = None
        self._archive_query = ""
        self._query_error: str | None = None

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
            self._update_preview_for_entry(self._filtered[0][1])

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="dismissed-agent-modal-container"):
            yield Label("Revive Agents", id="modal-title")
            yield _ReviveFilterInput(
                placeholder="Archive query...", id="dismissed-filter"
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
        self._same_session_agents = list(agents)
        self._all_dismissed = all_dismissed or agents
        self._entries = [_DismissedEntry(agent=agent) for agent in agents]
        self._step_counts = self._compute_step_counts()
        self._marked = {idx for idx in self._marked if idx < len(self._entries)}
        self._loading_archive = loading_archive
        self._query_error = None

        self._chat_contents.clear()
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        try:
            filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
            self._filtered = self._get_filtered_entries(filter_input.value)
        except Exception:
            self._filtered = list(enumerate(self._entries))

        self._rebuild_options()
        if self._filtered:
            self._update_preview_for_entry(self._filtered[0][1])
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

    def _format_archive_label(
        self, result: ArchiveQueryResult, orig_idx: int = -1
    ) -> Text:
        """Create styled text for an archive summary row."""
        text = Text()
        text.append(
            " \u25cf " if orig_idx in self._marked else "   ", style="bold #00D7D7"
        )
        if result.status == "DONE":
            text.append("\u2714 ", style="bold #5FD75F")
        elif result.status == "FAILED":
            text.append("\u2718 ", style="bold #FF5F5F")
        else:
            text.append("\u25cb ", style="dim")
        display_type = "workflow" if result.step_type else "agent"
        text.append(f"[{display_type}]", style="bold #87AFFF")
        text.append(" ")
        text.append(result.cl_name, style="bold")
        if result.agent_name:
            text.append("  ")
            text.append(f"@{result.agent_name}", style="#87D7FF")
        if result.start_time:
            text.append("  ")
            text.append(result.start_time[:16].replace("T", " "), style="dim")
        if result.model:
            text.append("  ")
            text.append(result.model, style="dim italic")
        if result.project_name:
            text.append("  ")
            text.append(result.project_name, style="dim")
        return text

    def _format_entry_label(self, entry: _DismissedEntry, orig_idx: int = -1) -> Text:
        """Create styled text for either a hydrated agent or summary row."""
        if entry.agent is not None:
            return self._format_agent_label(entry.agent, orig_idx)
        if entry.archive_result is not None:
            return self._format_archive_label(entry.archive_result, orig_idx)
        return Text("(invalid archive row)", style="dim")

    def _create_options(self, entries: list[_DismissedEntry]) -> list[Option]:
        """Create options from modal entries."""
        return [
            Option(self._format_entry_label(entry, i), id=str(i))
            for i, entry in enumerate(entries)
        ]

    def _create_options_or_placeholder(self) -> list[Option]:
        """Create agent options or a disabled loading/empty placeholder."""
        if self._entries:
            return self._create_options(self._entries)
        if self._loading_archive:
            return [
                Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
            ]
        return [
            Option(
                Text("No dismissed agents in this scope", style="dim"), disabled=True
            )
        ]

    def _get_filtered_entries(
        self, filter_text: str
    ) -> list[tuple[int, _DismissedEntry]]:
        """Get in-memory entries matching the legacy substring filter."""
        if not filter_text:
            return list(enumerate(self._entries))
        filter_lower = filter_text.lower()
        results: list[tuple[int, _DismissedEntry]] = []
        for i, entry in enumerate(self._entries):
            agent = entry.agent
            if agent is None:
                continue
            label = f"[{agent.display_type}] {agent.display_name}"
            if agent.agent_name:
                label += f" @{agent.agent_name}"
            if filter_lower in label.lower():
                results.append((i, entry))
                continue
            if i in self._chat_contents and filter_lower in self._chat_contents[i]:
                results.append((i, entry))
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

    def action_load_more(self) -> None:
        """Load the next page of archive-backed results."""
        if self._archive_query_provider is None or self._archive_cursor is None:
            return
        self.refresh_archive_query(self._archive_query, append=True)

    def refresh_archive_query(self, query: str, *, append: bool = False) -> bool:
        """Refresh entries from the archive provider.

        Invalid archive input leaves the previous valid result set intact.
        """
        provider = self._archive_query_provider
        if provider is None:
            return False

        cursor = self._archive_cursor if append else None
        try:
            page = provider.search(query, limit=self._page_size, cursor=cursor)
        except Exception as exc:
            self._query_error = str(exc)
            self._loading_archive = False
            self._update_hints_if_mounted()
            return False

        archive_entries = [
            _DismissedEntry(archive_result=result) for result in page.results
        ]
        if append:
            self._entries.extend(archive_entries)
        else:
            same_session_entries = [
                _DismissedEntry(agent=agent)
                for agent in self._same_session_agents
                if not query.strip()
            ]
            seen = {
                (entry.agent.cl_name, entry.agent.raw_suffix)
                for entry in same_session_entries
                if entry.agent is not None
            }
            deduped_archive_entries = []
            for entry in archive_entries:
                result = entry.archive_result
                if result is None:
                    continue
                key = (result.cl_name, result.raw_suffix)
                if key in seen:
                    continue
                seen.add(key)
                deduped_archive_entries.append(entry)
            self._entries = [*same_session_entries, *deduped_archive_entries]
            self._marked.clear()

        self._archive_query = query
        self._archive_cursor = page.next_cursor
        self._query_error = None
        self._loading_archive = False
        self._filtered = list(enumerate(self._entries))

        try:
            self._rebuild_options()
            if self._filtered:
                self._update_preview_for_entry(self._filtered[0][1])
            else:
                self._clear_preview()
            self._update_hints()
        except Exception:
            pass
        return True

    def _update_hints_if_mounted(self) -> None:
        try:
            self._update_hints()
        except Exception:
            pass

    def _rebuild_options(self) -> None:
        """Rebuild the option list to reflect mark state changes."""
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        old_highlighted = option_list.highlighted
        option_list.clear_options()
        if self._filtered:
            for orig_idx, entry in self._filtered:
                option_list.add_option(
                    Option(self._format_entry_label(entry, orig_idx), id=str(orig_idx))
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
        error = f" | {self._query_error}" if self._query_error else ""
        more = " | ^n: more" if self._archive_cursor is not None else ""
        if count:
            return (
                "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
                f"{more} | Enter: revive ({count}) | Esc/q: cancel{loading}{error}"
            )
        return (
            "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
            f"{more} | Enter: revive | Esc/q: cancel{loading}{error}"
        )

    def _update_hints(self) -> None:
        """Update the hints bar to reflect current mark count."""
        hints = self.query_one("#dismissed-agent-hints", Static)
        hints.update(self._hints_text())

    def _get_marked_agents(self) -> list[Agent]:
        """Get all marked agents in original order."""
        agents: list[Agent] = []
        for i in sorted(self._marked):
            if i >= len(self._entries):
                continue
            agent = self._hydrate_entry(self._entries[i])
            if agent is not None:
                agents.append(agent)
        return agents

    # --- Event handlers ---

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        if self._archive_query_provider is not None:
            self.refresh_archive_query(event.value)
            return

        self._filtered = self._get_filtered_entries(event.value)
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        option_list.clear_options()
        if self._filtered:
            for orig_idx, entry in self._filtered:
                option_list.add_option(
                    Option(self._format_entry_label(entry, orig_idx), id=str(orig_idx))
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
            self._update_preview_for_entry(self._filtered[0][1])
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
        filtered = self._filtered
        if not filtered:
            self.dismiss(None)
            return
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        highlighted = option_list.highlighted
        selected_entry: _DismissedEntry
        if highlighted is not None and 0 <= highlighted < len(filtered):
            selected_entry = filtered[highlighted][1]
        else:
            selected_entry = filtered[0][1]
        agent = self._hydrate_entry(selected_entry)
        self.dismiss([agent] if agent is not None else None)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update preview when highlighting changes."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._entries):
                self._update_preview_for_entry(self._entries[idx])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        # If agents are marked, revive all marked
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        # Otherwise, single selection
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._entries):
                agent = self._hydrate_entry(self._entries[idx])
                self.dismiss([agent] if agent is not None else None)

    # --- Preview ---

    def _hydrate_entry(self, entry: _DismissedEntry) -> Agent | None:
        """Hydrate an archive-backed entry on demand."""
        if entry.agent is not None:
            return entry.agent
        if entry.archive_result is None or self._archive_query_provider is None:
            return None

        try:
            agents = self._archive_query_provider.hydrate(entry.archive_result)
        except Exception:
            return None
        if not agents:
            return None

        self._merge_hydrated_agents(agents)
        selected = self._select_agent_from_hydrated_group(agents, entry.archive_result)
        entry.agent = selected
        return selected

    def _merge_hydrated_agents(self, agents: list[Agent]) -> None:
        """Add lazily hydrated archive rows to the modal's child lookup set."""
        seen = {agent.identity for agent in self._all_dismissed}
        for agent in agents:
            if agent.identity in seen:
                continue
            self._all_dismissed.append(agent)
            seen.add(agent.identity)
        self._step_counts = self._compute_step_counts()

    def _select_agent_from_hydrated_group(
        self,
        agents: list[Agent],
        result: ArchiveQueryResult,
    ) -> Agent | None:
        for agent in agents:
            if (
                agent.raw_suffix == result.raw_suffix
                and agent.step_index == result.step_index
                and agent.is_workflow_child == result.is_workflow_child
            ):
                return agent
        for agent in agents:
            if agent.raw_suffix == result.raw_suffix and not agent.is_workflow_child:
                return agent
        return agents[0]

    def _update_preview_for_entry(self, entry: _DismissedEntry) -> None:
        """Update preview, hydrating archive rows only when highlighted."""
        agent = self._hydrate_entry(entry)
        if agent is None and entry.archive_result is not None:
            self._update_archive_summary_preview(entry.archive_result)
            return
        if agent is not None:
            self._update_preview(agent)
        else:
            self._clear_preview()

    def _update_archive_summary_preview(self, result: ArchiveQueryResult) -> None:
        """Show compact metadata when a bundle cannot be hydrated."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)
            meta = Text()
            meta.append("Archive result\n\n", style="bold")
            meta.append(f"  {'Status':<12}", style="bold")
            meta.append(
                f"{result.status}\n", style=self._get_status_style(result.status)
            )
            meta.append(f"  {'CL':<12}", style="bold")
            meta.append(f"{result.cl_name}\n", style="dim")
            if result.agent_name:
                meta.append(f"  {'Agent':<12}", style="bold")
                meta.append(f"@{result.agent_name}\n", style="#87D7FF")
            if result.project_name:
                meta.append(f"  {'Project':<12}", style="bold")
                meta.append(f"{result.project_name}\n", style="dim")
            if result.model:
                meta.append(f"  {'Model':<12}", style="bold")
                meta.append(f"{result.model}\n", style="dim italic")
            metadata_widget.update(meta)
            content_widget.update(
                Text("(bundle preview unavailable)", style="dim italic")
            )
        except Exception:
            pass

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
