"""Dismissed agent selection modal for the ace TUI."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models.agent import Agent
from ..util.debounce import DetailPanelDebouncer
from .base import OptionListNavigationMixin
from .revive_agent_filter_input import ReviveFilterInput
from .revive_agent_formatting import ReviveAgentFormattingMixin
from .revive_agent_preview import ReviveAgentPreviewMixin
from .revive_agent_types import ArchiveQueryProvider, DismissedEntry

_ArchiveQueryProvider = ArchiveQueryProvider
_DismissedEntry = DismissedEntry
_ReviveFilterInput = ReviveFilterInput

_ARCHIVE_QUERY_DEBOUNCE_S = 0.15
_ARCHIVE_WORKER_GROUP = "revive-archive"


class DismissedAgentSelectModal(
    ReviveAgentPreviewMixin,
    ReviveAgentFormattingMixin,
    OptionListNavigationMixin,
    ModalScreen[list[Agent] | None],
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
        archive_query_provider: ArchiveQueryProvider | None = None,
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
        self._entries: list[DismissedEntry] = [
            DismissedEntry(agent=agent) for agent in agents
        ]
        self._filtered: list[tuple[int, DismissedEntry]] = list(
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
        self._archive_debouncer: DetailPanelDebouncer | None = None
        self._pending_archive_query: str | None = None
        self._pending_archive_append = False
        self._inflight_archive_query: str | None = None

    def on_mount(self) -> None:
        """Focus the filter input and pre-load chat contents."""
        for i, agent in enumerate(self.agents):
            content = agent.get_response_content()
            if content:
                self._chat_contents[i] = content.lower()

        filter_input = self.query_one("#dismissed-filter", ReviveFilterInput)
        filter_input.focus()
        if self._filtered:
            self._update_preview_for_entry(self._filtered[0][1])

        if self._archive_query_provider is not None:
            self._archive_debouncer = DetailPanelDebouncer(
                self.app, delay_s=_ARCHIVE_QUERY_DEBOUNCE_S
            )
            self._start_archive_worker("", append=False)

    def on_unmount(self) -> None:
        """Cancel pending debounce and any in-flight archive worker."""
        if self._archive_debouncer is not None:
            self._archive_debouncer.cancel()
        try:
            self.workers.cancel_group(self, _ARCHIVE_WORKER_GROUP)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="dismissed-agent-modal-container"):
            yield Label("Revive Agents", id="modal-title")
            yield ReviveFilterInput(
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
        self._entries = [DismissedEntry(agent=agent) for agent in agents]
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
            filter_input = self.query_one("#dismissed-filter", ReviveFilterInput)
            self._filtered = self._get_filtered_entries(filter_input.value)
        except Exception:
            self._filtered = list(enumerate(self._entries))

        self._rebuild_options()
        if self._filtered:
            self._update_preview_for_entry(self._filtered[0][1])
        else:
            self._clear_preview()
        self._update_hints()

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

    def action_load_more(self) -> None:
        """Load the next page of archive-backed results."""
        if self._archive_query_provider is None or self._archive_cursor is None:
            return
        self._schedule_archive_query(self._archive_query, append=True)

    def refresh_archive_query(self, query: str, *, append: bool = False) -> bool:
        """Refresh entries from the archive provider.

        Invalid archive input leaves the previous valid result set intact.
        Runs the provider call synchronously on the calling thread. The
        modal also exposes :meth:`_schedule_archive_query` for the typing
        path, which debounces and runs the search on a worker thread.
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

        self._apply_archive_page(query, append, page)
        return True

    def _apply_archive_page(self, query: str, append: bool, page: Any) -> None:
        """Merge a provider result page into the modal state (UI thread)."""
        archive_entries = [
            DismissedEntry(archive_result=result) for result in page.results
        ]
        if append:
            self._entries.extend(archive_entries)
        else:
            same_session_entries = [
                DismissedEntry(agent=agent)
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

    def _schedule_archive_query(self, query: str, *, append: bool = False) -> None:
        """Debounce and run an archive search on a worker thread."""
        debouncer = self._archive_debouncer
        if debouncer is None:
            self.refresh_archive_query(query, append=append)
            return

        self._pending_archive_query = query
        self._pending_archive_append = append
        self._loading_archive = True
        self._query_error = None
        self._update_hints_if_mounted()
        debouncer.schedule(self._run_pending_archive_query)

    def _run_pending_archive_query(self) -> None:
        """Fire the most recently scheduled archive search on a worker."""
        query = self._pending_archive_query
        if query is None:
            return
        append = self._pending_archive_append
        self._pending_archive_query = None
        self._pending_archive_append = False
        self._start_archive_worker(query, append=append)

    def _start_archive_worker(self, query: str, *, append: bool) -> None:
        provider = self._archive_query_provider
        if provider is None:
            return
        cursor = self._archive_cursor if append else None
        page_size = self._page_size
        self._inflight_archive_query = query
        app = self.app

        def _search() -> None:
            try:
                page = provider.search(query, limit=page_size, cursor=cursor)
            except Exception as exc:
                error = str(exc)
                app.call_from_thread(self._on_archive_query_failed, query, error)
                return
            app.call_from_thread(self._on_archive_page_ready, query, append, page)

        try:
            self.run_worker(
                _search,
                thread=True,
                exclusive=True,
                group=_ARCHIVE_WORKER_GROUP,
            )
        except Exception as exc:
            self._query_error = str(exc)
            self._loading_archive = False
            self._update_hints_if_mounted()

    def _flush_pending_archive_query(self) -> bool:
        """Cancel the debounce timer and run the pending search synchronously."""
        debouncer = self._archive_debouncer
        if debouncer is None or self._pending_archive_query is None:
            return False
        query = self._pending_archive_query
        append = self._pending_archive_append
        debouncer.cancel()
        self._pending_archive_query = None
        self._pending_archive_append = False
        return self.refresh_archive_query(query, append=append)

    def _on_archive_page_ready(self, query: str, append: bool, page: Any) -> None:
        if query != self._inflight_archive_query:
            return
        self._inflight_archive_query = None
        self._apply_archive_page(query, append, page)

    def _on_archive_query_failed(self, query: str, error: str) -> None:
        if query != self._inflight_archive_query:
            return
        self._inflight_archive_query = None
        self._query_error = error
        self._loading_archive = False
        self._update_hints_if_mounted()

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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input change."""
        if self._archive_query_provider is not None:
            self._schedule_archive_query(event.value)
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
        if self._archive_query_provider is not None:
            self._flush_pending_archive_query()
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        filtered = self._filtered
        if not filtered:
            self.dismiss(None)
            return
        option_list = self.query_one("#dismissed-agent-list", OptionList)
        highlighted = option_list.highlighted
        selected_entry: DismissedEntry
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
        if self._marked:
            self.dismiss(self._get_marked_agents())
            return
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._entries):
                agent = self._hydrate_entry(self._entries[idx])
                self.dismiss([agent] if agent is not None else None)
