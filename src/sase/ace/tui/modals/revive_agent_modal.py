"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.project_display_names import humanize_vcs_refs_in_text

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

_DismissedPageLoader = Callable[[], tuple[list[Agent], list[Agent], bool]]


def _response_filter_corpus(content: str) -> str:
    """Return lowercased response text containing canonical and displayed refs."""
    display = humanize_vcs_refs_in_text(content)
    if display != content:
        content = f"{content}\n{display}"
    return content.lower()


def _agent_filter_label(agent: Agent) -> str:
    """Return searchable row text, including display and canonical names."""
    parts = [f"[{agent.display_type}] {agent.display_name}", agent.cl_name]
    if agent.project_file:
        project_name = Path(agent.project_file).parent.name
        parts.append(project_name)
        if agent.project_display_name and agent.project_display_name != project_name:
            parts.append(agent.project_display_name)
    if agent.presented_agent_name:
        parts.append(f"@{agent.presented_agent_name}")
    return " ".join(part for part in parts if part)


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
        Binding("ctrl+k", "load_more", "Load More", priority=True),
        Binding("tab", "toggle_mark", "Mark", priority=True),
        Binding("ctrl+a", "toggle_all", "Mark All", priority=True),
    ]

    def __init__(
        self,
        agents: list[Agent],
        *,
        all_dismissed: list[Agent] | None = None,
        loading_archive: bool = False,
        page_loader: _DismissedPageLoader | None = None,
        page_size: int = 250,
    ) -> None:
        """Initialize the modal."""
        super().__init__()
        self.agents = agents
        self._all_dismissed = all_dismissed or agents
        self._filter_labels: dict[int, str] = {}
        self._chat_contents: dict[int, str] = {}
        self._filtered: list[tuple[int, Agent]] = list(enumerate(agents))
        self._step_counts: dict[str, int] = self._compute_step_counts()
        self._marked: set[int] = set()
        self._loading_archive = loading_archive
        self._page_loader = page_loader
        self._page_size = page_size
        self._page_loading = False
        self._page_exhausted = page_loader is None
        self._initial_loading = True

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
        """Focus immediately and load archive/filter corpora off the modal pump."""
        filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
        filter_input.focus()
        self.run_worker(
            self._load_initial_async(),
            exclusive=True,
            group="dismissed-archive-load",
        )

    async def _load_initial_async(self) -> None:
        """Populate initial archive rows/corpora without blocking modal input."""
        if self._page_loader is not None:
            await self._load_more_async(preserve_highlight=False)
            self._initial_loading = False
            self._rebuild_options()
            self._update_preview_for_current_highlight()
            return

        try:
            filter_labels, response_corpora = await asyncio.to_thread(
                self._filter_corpora_for_agents, self.agents
            )
        except Exception as exc:
            self.notify(
                f"Failed to load dismissed agent details: {exc}", severity="error"
            )
            return

        self._filter_labels = filter_labels
        self._chat_contents = response_corpora
        self._initial_loading = False
        filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
        self._filtered = self._get_filtered_agents(filter_input.value)
        self._rebuild_options()
        self._update_preview_for_current_highlight()

    def on_key(self, event: events.Key) -> None:
        """Intercept Ctrl+K before the focused filter input consumes it."""
        if event.key == "ctrl+k":
            event.prevent_default()
            event.stop()
            self.action_load_more()

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
        page_exhausted: bool | None = None,
        preserve_highlight: bool = False,
        filter_labels: dict[int, str] | None = None,
        response_corpora: dict[int, str] | None = None,
    ) -> None:
        """Replace modal contents after an on-demand bundle load."""
        preserve_identity = (
            self._highlighted_agent_identity() if preserve_highlight else None
        )
        marked_identities = {
            self.agents[idx].identity for idx in self._marked if idx < len(self.agents)
        }
        self.agents = agents
        self._all_dismissed = all_dismissed or agents
        self._step_counts = self._compute_step_counts()
        self._marked = {
            idx
            for idx, agent in enumerate(self.agents)
            if agent.identity in marked_identities
        }
        self._loading_archive = loading_archive
        if page_exhausted is not None:
            self._page_exhausted = page_exhausted

        self._filter_labels = filter_labels or {}
        self._chat_contents = response_corpora or {}

        try:
            filter_input = self.query_one("#dismissed-filter", _ReviveFilterInput)
            self._filtered = self._get_filtered_agents(filter_input.value)
        except Exception:
            self._filtered = list(enumerate(self.agents))

        if self.is_mounted:
            self._apply_agents_to_widgets(preserve_identity)
        else:
            # A worker can finish while the modal is still mounting. Defer the
            # widget refresh so the loaded page is not stranded in model state.
            self.call_after_refresh(self._apply_agents_to_widgets, preserve_identity)

    def _apply_agents_to_widgets(
        self,
        highlight_identity: tuple[object, str, str | None] | None = None,
    ) -> None:
        """Render current modal model state into the mounted widgets.

        Idempotent and driven entirely by current model state, so the deferred
        initial-page refresh and later Ctrl+K load-more share one apply path.
        """
        if not self.is_mounted:
            return
        self._rebuild_options(highlight_identity=highlight_identity)
        self._update_preview_for_current_highlight()
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
        if self._initial_loading:
            return [placeholder_option(loading_archive=True)]
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
            label = self._filter_labels.get(i)
            if label is None:
                label = _agent_filter_label(agent)
            if filter_lower in label.lower():
                results.append((i, agent))
                continue
            if i in self._chat_contents and filter_lower in self._chat_contents[i]:
                results.append((i, agent))
        return results

    @staticmethod
    def _filter_corpora_for_agents(
        agents: list[Agent],
    ) -> tuple[dict[int, str], dict[int, str]]:
        """Prepare reusable label/response text outside keystroke handling."""
        labels: dict[int, str] = {}
        responses: dict[int, str] = {}
        for i, agent in enumerate(agents):
            labels[i] = _agent_filter_label(agent).lower()
            content = agent.get_response_content()
            if content:
                responses[i] = _response_filter_corpus(content)
        return labels, responses

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

    def _highlighted_agent_identity(self) -> tuple[object, str, str | None] | None:
        """Return the identity for the currently highlighted filtered row."""
        try:
            option_list = self.query_one("#dismissed-agent-list", OptionList)
            highlighted = option_list.highlighted
        except Exception:
            return None
        if highlighted is None or not (0 <= highlighted < len(self._filtered)):
            return None
        return self._filtered[highlighted][1].identity

    def _rebuild_options(
        self,
        *,
        highlight_identity: tuple[object, str, str | None] | None = None,
    ) -> None:
        """Rebuild the option list to reflect mark state changes."""
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        old_highlighted = option_list.highlighted
        option_list.clear_options()
        if self._initial_loading:
            option_list.add_option(placeholder_option(loading_archive=True))
        elif self._filtered:
            for orig_idx, agent in self._filtered:
                option_list.add_option(
                    Option(self._format_agent_label(agent, orig_idx), id=str(orig_idx))
                )
        elif self._loading_archive:
            option_list.add_option(placeholder_option(loading_archive=True))
        else:
            option_list.add_option(placeholder_option(loading_archive=False))
        if not self._filtered:
            return
        next_highlighted: int | None = None
        if highlight_identity is not None:
            for idx, (_, agent) in enumerate(self._filtered):
                if agent.identity == highlight_identity:
                    next_highlighted = idx
                    break
        if next_highlighted is None and old_highlighted is not None:
            if 0 <= old_highlighted < len(self._filtered):
                next_highlighted = old_highlighted
        if next_highlighted is None:
            next_highlighted = 0
        if next_highlighted is not None:
            option_list.highlighted = next_highlighted

    def _update_preview_for_current_highlight(self) -> None:
        """Update preview for the highlighted filtered row, or clear it."""
        if not self._filtered:
            self._clear_preview()
            return
        try:
            option_list = self.query_one("#dismissed-agent-list", OptionList)
            highlighted = option_list.highlighted
        except Exception:
            highlighted = None
        idx = highlighted if highlighted is not None else 0
        idx = min(max(idx, 0), len(self._filtered) - 1)
        self._update_preview(self._filtered[idx][1])

    def _hints_text(self) -> str:
        count = len(self._marked)
        paging = ""
        if self._page_loader is not None:
            if self._page_loading:
                paging = f" | loading +{self._page_size}"
            elif not self._page_exhausted:
                paging = f" | ^k: +{self._page_size} more"
        elif self._loading_archive:
            paging = " | archive loading"
        if count:
            return (
                "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
                f" | Enter: revive ({count}) | Esc/q: cancel{paging}"
            )
        return (
            "j/k: navigate | tab: mark | ^a: all | ^d/^u: scroll"
            f" | Enter: revive | Esc/q: cancel{paging}"
        )

    def _update_hints(self) -> None:
        """Update the hints bar to reflect current mark count."""
        hints = self.query_one("#dismissed-agent-hints", Static)
        hints.update(self._hints_text())

    def _get_marked_agents(self) -> list[Agent]:
        """Get all marked agents in original order."""
        return [self.agents[i] for i in sorted(self._marked) if i < len(self.agents)]

    async def _load_more_async(self, *, preserve_highlight: bool = True) -> None:
        """Load another dismissed-archive page off the Textual event loop."""
        if self._page_loader is None or self._page_loading or self._page_exhausted:
            self._update_hints()
            return
        self._page_loading = True
        self._loading_archive = True
        self._update_hints()
        if not self.agents:
            self._rebuild_options()
        try:
            agents, all_dismissed, exhausted = await asyncio.to_thread(
                self._page_loader
            )
            filter_labels, response_corpora = await asyncio.to_thread(
                self._filter_corpora_for_agents, agents
            )
        except Exception as exc:
            self.notify(f"Failed to load dismissed archive: {exc}", severity="error")
            self._page_loading = False
            self._loading_archive = False
            self._update_hints()
            if not self.agents:
                self._rebuild_options()
            return
        finally:
            self._page_loading = False

        self.set_agents(
            agents,
            all_dismissed=all_dismissed,
            loading_archive=False,
            page_exhausted=exhausted,
            preserve_highlight=preserve_highlight,
            filter_labels=filter_labels,
            response_corpora=response_corpora,
        )

    def action_load_more(self) -> None:
        """Load the next dismissed-archive page."""
        if self._page_loader is None or self._page_loading or self._page_exhausted:
            self._update_hints()
            return
        self.run_worker(
            self._load_more_async(),
            exclusive=True,
            group="dismissed-archive-load",
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        self._filtered = self._get_filtered_agents(event.value)
        if self._initial_loading:
            self._rebuild_options()
            self._clear_preview()
            self._update_hints()
            return
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
