"""Reusable History pane and its shared controller logic.

This module owns the prompt-history state and loading logic shared by the
standalone :class:`PromptHistoryModal` and the tabbed :class:`PromptsModal`
overlay. The screen-specific behavior previously in
``prompt_history_modal.py`` now lives in
:class:`PromptHistoryControllerMixin` so both hosts keep identical behavior;
the modal keeps its exact DOM while :class:`HistoryPane` renders only the
filter and list/preview panels (the overlay shell owns the heading, tab
strip, and footer).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.config import get_ace_page_size
from sase.core.prompt_history_filter_wire import (
    CompiledPromptHistoryQuery,
    PromptHistoryRowFacts,
)
from sase.history.prompt import (
    PromptHistoryPage,
    PromptHistoryPageCursor,
    load_prompt_record_page,
)
from sase.history.prompt_history_project_filter import (
    PromptHistoryProjectCatalog,
    build_prompt_history_seed_from_draft,
    prepare_prompt_history_row_facts,
)
from sase.history.prompt_metadata import (
    summarize_prompt_for_list,
    summarize_prompt_for_preview,
)
from sase.project_display_names import humanize_vcs_refs_in_text

from ._prompt_history_interactions import PromptHistoryInteractionMixin
from ._prompt_history_list_state import PromptHistoryListStateMixin
from ._prompt_history_models import (
    PromptDisplayItem,
    PromptHistoryResult,
    display_text_for_item as _display_text_for_item,
)
from ._prompt_history_preview import (
    build_prompt_history_metadata,
)
from ._prompt_history_rows import (
    _FALLBACK_PREVIEW_WIDTH,
    create_prompt_history_label as _render_prompt_history_label,
    prompt_history_header_text as _prompt_history_header_text,
    prompt_preview_width_for_list_content as _prompt_preview_width_for_list_content,
)
from .base import FilterInput, OptionListNavigationMixin

if TYPE_CHECKING:
    from sase.core.prompt_history_filter_wire import PromptHistorySeed


@dataclass(frozen=True, slots=True)
class PromptHistoryLoadedPage:
    """One fetched page so unload can drop it and refetch from the same cursor."""

    item_count: int
    resume_cursor: PromptHistoryPageCursor | None


def create_prompt_history_label(
    item: PromptDisplayItem,
    *,
    preview_width: int = _FALLBACK_PREVIEW_WIDTH,
) -> Text:
    """Create a single-line styled label for a prompt history item."""
    return _render_prompt_history_label(
        item,
        preview_width=preview_width,
        summarize_for_list=summarize_prompt_for_list,
    )


class _TabCycleFilterInput(FilterInput):
    """History filter that can yield ``[``/``]`` to overlay tab cycling.

    When ``tab_cycle_enabled`` is set (only inside the tabbed overlay), the
    input intercepts brackets in :meth:`on_key` — which MRO dispatch runs
    before ``Input._on_key`` inserts text — and posts a
    :class:`HistoryPane.CycleTabRequested` message instead; every other key
    types normally. The standalone modal leaves the flag off, preserving
    exact legacy filter behavior.
    """

    def __init__(
        self, *args: Any, tab_cycle_enabled: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._tab_cycle_enabled = tab_cycle_enabled

    def on_key(self, event: events.Key) -> None:
        """Cycle overlay tabs on brackets instead of inserting them."""
        if self._tab_cycle_enabled and event.character in ("[", "]"):
            event.prevent_default()
            event.stop()
            self.post_message(
                HistoryPane.CycleTabRequested(-1 if event.character == "[" else 1)
            )

    def check_consume_key(self, key: str, character: str | None) -> bool:
        """Decline bracket keys when the overlay owns tab cycling."""
        if self._tab_cycle_enabled and character in ("[", "]"):
            return False
        return super().check_consume_key(key, character)


HISTORY_BINDINGS: list[Any] = [
    *OptionListNavigationMixin.NAVIGATION_BINDINGS,
    Binding("ctrl+j", "load_more", "Load More", priority=True),
    Binding("ctrl+k", "unload", "Unload", priority=True),
    ("ctrl+g", "edit_first", "Edit in editor"),
    ("ctrl+x", "toggle_cancelled", "Toggle cancelled"),
    ("ctrl+y", "copy_and_cancel", "Copy & cancel"),
]


class PromptHistoryControllerMixin:
    """Shared history loading state, paging, and layout pieces.

    Hosts provide ``_emit_result`` and compose the shared pieces. The
    standalone modal keeps its title and footer; the overlay pane renders
    only the filter and panels.
    """

    if TYPE_CHECKING:
        _tab_cycle_brackets: bool

        def _emit_result(self, result: PromptHistoryResult | None = None) -> None: ...

        def _apply_seed(self, seed: PromptHistorySeed) -> None: ...

        def _clear_preview(self) -> None: ...

        def _create_initial_options(self) -> list[Option]: ...

        @staticmethod
        def _default_scope_hint_text() -> Text: ...

        def _get_filtered_items(self, filter_text: str) -> list[PromptDisplayItem]: ...

        def _hints_text(self) -> str: ...

        def _history_count_label(self) -> str: ...

        def _refresh_options(
            self,
            *,
            preserve_highlight: bool = False,
            preview_width: int | None = None,
        ) -> None: ...

        def _refresh_options_for_current_width(self) -> None: ...

        def _update_history_count_label(self) -> None: ...

        def _update_preview(self, item: PromptDisplayItem) -> None: ...

        def _update_scope_hint(self) -> None: ...

    _option_list_id = "prompt-history-list"
    _tab_cycle_brackets = False

    def _init_history_controller(
        self,
        show_cancelled: bool = False,
        initial_filter: str = "",
        prompt_seed: str | None = None,
    ) -> None:
        """Initialize the prompt history controller state.

        Args:
            show_cancelled: Whether to show cancelled prompts by default.
            initial_filter: An already-authored query to pre-fill in the
                modal filter.
            prompt_seed: An unauthored prompt draft (Ctrl+K) resolved into
                the initial ``project:`` + text query asynchronously, once
                the project-identity snapshot loads. Mutually exclusive with
                *initial_filter*.
        """
        if initial_filter and prompt_seed is not None:
            raise ValueError(
                "PromptHistoryModal accepts either initial_filter or "
                "prompt_seed, never both"
            )
        self._all_items: list[PromptDisplayItem] = []
        self._filtered_items: list[PromptDisplayItem] = []
        self._row_facts: list[PromptHistoryRowFacts] = []
        self._show_cancelled = show_cancelled
        self._initial_filter = initial_filter
        self._prompt_seed = prompt_seed
        self._catalog: PromptHistoryProjectCatalog | None = None
        self._last_compiled_query: CompiledPromptHistoryQuery | None = None
        self._filter_edit_generation = 0
        self._seed_hint_text: str | None = None
        self._seed_applied_value: str | None = None
        self._last_preview_width_budget = _FALLBACK_PREVIEW_WIDTH
        self._next_cursor: PromptHistoryPageCursor | None = None
        self._history_exhausted = False
        self._history_loaded_once = False
        self._history_loading = False
        self._page_size = get_ace_page_size()
        self._loaded_pages: list[PromptHistoryLoadedPage] = []

    def _create_styled_label(self, item: PromptDisplayItem) -> Text:
        """Create styled text for a prompt list item."""
        return create_prompt_history_label(
            item,
            preview_width=self._last_preview_width_budget,
        )

    def _resolved_page_size(self) -> int:
        """Return the configured page size, falling back if init was skipped."""
        page_size = getattr(self, "_page_size", None)
        if type(page_size) is int and page_size >= 1:
            return page_size
        return get_ace_page_size()

    def _load_page(self) -> PromptHistoryPage:
        """Load the next page of prompt history records."""
        return load_prompt_record_page(
            page_size=self._resolved_page_size(),
            cursor=self._next_cursor,
            include_cancelled=True,
        )

    def _append_page(self, page: PromptHistoryPage) -> None:
        """Append a loaded page to modal state."""
        resume_cursor = self._next_cursor
        catalog = self._catalog or PromptHistoryProjectCatalog(entries=())
        for record in page.records:
            entry = record.to_entry()
            display_text = humanize_vcs_refs_in_text(entry.text)
            index = len(self._all_items)
            self._all_items.append(
                PromptDisplayItem(
                    entry=entry,
                    marker="x" if entry.cancelled else " ",
                    display_text=display_text,
                )
            )
            self._row_facts.append(
                prepare_prompt_history_row_facts(
                    index, entry.text, display_text, catalog
                )
            )
        if not hasattr(self, "_loaded_pages"):
            self._loaded_pages = []
        self._loaded_pages.append(
            PromptHistoryLoadedPage(
                item_count=len(page.records),
                resume_cursor=resume_cursor,
            )
        )
        self._next_cursor = page.next_cursor
        self._history_exhausted = page.exhausted
        self._history_loaded_once = True

    # -- layout --------------------------------------------------------------

    def _compose_history_title(self) -> ComposeResult:
        yield Label("Select Prompt from History", id="modal-title")

    def _compose_history_filter(self) -> ComposeResult:
        yield _TabCycleFilterInput(
            value=self._initial_filter,
            placeholder="Type to filter loaded prompts...",
            id="prompt-history-filter-input",
            tab_cycle_enabled=self._tab_cycle_brackets,
        )
        yield Static(
            self._default_scope_hint_text(),
            id="prompt-history-scope-hint",
        )

    def _compose_history_panels(self) -> ComposeResult:
        with Horizontal(id="prompt-history-panels"):
            with Vertical(id="prompt-history-list-panel"):
                yield Label(
                    self._history_count_label(),
                    id="prompt-history-list-label",
                )
                with Vertical(id="prompt-history-table"):
                    yield Static(
                        _prompt_history_header_text(),
                        id="prompt-history-columns",
                    )
                    yield OptionList(
                        *self._create_initial_options(),
                        id="prompt-history-list",
                    )
            with Vertical(id="prompt-history-preview-panel"):
                yield Label("Preview", id="prompt-history-preview-label")
                with VerticalScroll(id="prompt-history-preview-scroll"):
                    yield Static("", id="prompt-history-preview", markup=False)
                    yield Static("", id="prompt-history-metadata")

    def _compose_history_footer(self) -> ComposeResult:
        yield Static(
            self._hints_text(),
            id="prompt-history-hints",
        )

    def _compose_history_modal_body(self) -> ComposeResult:
        """Full standalone-modal body: title, filter, panels, and footer."""
        with Container(id="prompt-history-modal-container"):
            yield from self._compose_history_title()
            yield from self._compose_history_filter()
            yield from self._compose_history_panels()
            yield from self._compose_history_footer()

    def _on_history_mount(self) -> None:
        """Focus immediately and load identity + the first page outside the pump."""
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)  # type: ignore[attr-defined]
        filter_input.focus()
        filter_input.cursor_position = len(filter_input.value)
        self.run_worker(  # type: ignore[attr-defined]
            self._open_history_async(),
            exclusive=True,
            group="prompt-history-load",
        )

    def focus_history_filter(self) -> None:
        """Focus the history filter, falling back silently when unmounted."""
        try:
            self.query_one("#prompt-history-filter-input", FilterInput).focus()  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _open_history_async(self) -> None:
        """Load the identity snapshot, resolve a pending seed, then page one.

        Escape and typing stay responsive throughout: this coroutine only
        awaits off-thread work and never blocks the event loop. A pending
        Ctrl+K seed is applied only if ``_filter_edit_generation`` has not
        advanced since right after the snapshot loaded, so a keystroke (or a
        deliberate clear) that lands during the awaited resolution wins over
        the seed instead of being clobbered by it.
        """
        self._catalog = await asyncio.to_thread(PromptHistoryProjectCatalog.load)
        if self._prompt_seed is not None:
            generation_at_snapshot = self._filter_edit_generation
            seed = await asyncio.to_thread(
                build_prompt_history_seed_from_draft,
                self._prompt_seed,
                self._catalog,
            )
            unedited = self._filter_edit_generation == generation_at_snapshot
            if self.is_mounted and unedited:  # type: ignore[attr-defined]
                self._apply_seed(seed)
        await self._load_more_async(preserve_highlight=False)

    async def _load_more_async(self, *, preserve_highlight: bool = True) -> None:
        """Load another bounded prompt-history page off the event loop."""
        if self._history_loading or self._history_exhausted:
            return
        self._history_loading = True
        self._update_history_count_label()
        try:
            page = await asyncio.to_thread(self._load_page)
        except Exception as exc:
            self.notify(f"Failed to load prompt history: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        finally:
            self._history_loading = False

        self._append_page(page)
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)  # type: ignore[attr-defined]
        self._filtered_items = self._get_filtered_items(filter_input.value)
        self._update_history_count_label()
        self._update_scope_hint()
        self._refresh_options(preserve_highlight=preserve_highlight)
        if self._filtered_items:
            option_list = self.query_one("#prompt-history-list", OptionList)  # type: ignore[attr-defined]
            highlighted = option_list.highlighted
            idx = highlighted if highlighted is not None else 0
            idx = min(max(idx, 0), len(self._filtered_items) - 1)
            option_list.highlighted = idx
            self._update_preview(self._filtered_items[idx])
            self.call_after_refresh(self._refresh_options_for_current_width)  # type: ignore[attr-defined]
        else:
            self._clear_preview()

    def action_load_more(self) -> None:
        """Load the next prompt-history page."""
        if self._history_loading or self._history_exhausted:
            self._update_history_count_label()
            return
        self.run_worker(  # type: ignore[attr-defined]
            self._load_more_async(),
            exclusive=True,
            group="prompt-history-load",
        )

    def action_unload(self) -> None:
        """Drop the last loaded prompt-history page and rewind its cursor."""
        pages = getattr(self, "_loaded_pages", None)
        if not pages or len(pages) <= 1 or getattr(self, "_history_loading", False):
            self._update_history_count_label()
            return
        last = pages.pop()
        if last.item_count:
            del self._all_items[-last.item_count :]
            del self._row_facts[-last.item_count :]
        self._next_cursor = last.resume_cursor
        self._history_exhausted = False
        try:
            filter_input = self.query_one("#prompt-history-filter-input", FilterInput)  # type: ignore[attr-defined]
            filter_text = filter_input.value
        except Exception:
            filter_text = ""
        self._filtered_items = self._get_filtered_items(filter_text)
        self._update_history_count_label()
        self._update_scope_hint()
        try:
            self._refresh_options(preserve_highlight=True)
        except Exception:
            return
        if self._filtered_items:
            option_list = self.query_one("#prompt-history-list", OptionList)  # type: ignore[attr-defined]
            highlighted = option_list.highlighted
            idx = highlighted if highlighted is not None else 0
            idx = min(max(idx, 0), len(self._filtered_items) - 1)
            option_list.highlighted = idx
            self._update_preview(self._filtered_items[idx])
        else:
            self._clear_preview()


class HistoryPane(
    PromptHistoryControllerMixin,
    PromptHistoryListStateMixin,
    PromptHistoryInteractionMixin,
    OptionListNavigationMixin,
    Widget,
):
    """Reusable history filter/list pane for the tabbed Prompts overlay.

    The overlay shell owns the heading, tab strip, and footer; this pane
    renders only the filter and list/preview panels and reports outcomes as
    :class:`HistoryPane.Selected` instead of dismissing a screen. History
    disk I/O starts on mount, so the shell mounts this pane lazily on first
    activation.
    """

    class Selected(Message):
        """Posted when the history pane resolves to a result or cancel."""

        def __init__(self, result: PromptHistoryResult | None) -> None:
            super().__init__()
            self.result = result

    class CycleTabRequested(Message):
        """Posted when ``[``/``]`` is typed in the overlay filter."""

        def __init__(self, step: int) -> None:
            super().__init__()
            self.step = step

    BINDINGS = HISTORY_BINDINGS

    def __init__(
        self,
        show_cancelled: bool = False,
        initial_filter: str = "",
        prompt_seed: str | None = None,
        *,
        tab_cycle_brackets: bool = False,
    ) -> None:
        super().__init__()
        self._tab_cycle_brackets = tab_cycle_brackets
        self._init_history_controller(
            show_cancelled=show_cancelled,
            initial_filter=initial_filter,
            prompt_seed=prompt_seed,
        )

    def dismiss(self, result: PromptHistoryResult | None = None) -> None:
        """Translate screen-style cancel/submit into a bubbled selection."""
        self.post_message(HistoryPane.Selected(result))

    def _emit_result(self, result: PromptHistoryResult | None = None) -> None:
        self.dismiss(result)

    def compose(self) -> ComposeResult:
        with Vertical(id="history-pane-body"):
            yield from self._compose_history_filter()
            yield from self._compose_history_panels()

    def on_mount(self) -> None:
        self._on_history_mount()


__all__ = [
    "HISTORY_BINDINGS",
    "HistoryPane",
    "PromptHistoryControllerMixin",
    "PromptHistoryLoadedPage",
    "create_prompt_history_label",
]
