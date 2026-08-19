"""Prompt history selection modal with filtering for the ace TUI."""

import asyncio
from dataclasses import dataclass

from sase.ace.config import get_ace_page_size
from sase.history.prompt import (
    PromptHistoryPage,
    PromptHistoryPageCursor,
    load_prompt_record_page,
)
from sase.history.prompt_metadata import (
    summarize_prompt_for_list,
    summarize_prompt_for_preview,
)
from sase.project_display_names import humanize_vcs_refs_in_text
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ._prompt_history_models import (
    PromptDisplayItem,
    PromptHistoryAction,
    PromptHistoryResult,
)
from ._prompt_history_preview import (
    append_metadata_row as _append_metadata_row,
    build_prompt_history_metadata,
    preview_project_value as _preview_project_value,
)
from ._prompt_history_rows import (
    _FALLBACK_PREVIEW_WIDTH,
    _MIN_PREVIEW_WIDTH,
    _OPTION_HORIZONTAL_PADDING_WIDTH,
    _PROMPT_COL_START,
    create_prompt_history_label as _render_prompt_history_label,
    ellipsize_right as _ellipsize_right,
    format_history_timestamp as _format_history_timestamp,
    prompt_history_header_text as _prompt_history_header_text,
    prompt_preview_width_for_list_content as _prompt_preview_width_for_list_content,
)
from .base import FilterInput, OptionListNavigationMixin

_PromptDisplayItem = PromptDisplayItem


@dataclass(frozen=True, slots=True)
class _PromptHistoryLoadedPage:
    """One fetched page so unload can drop it and refetch from the same cursor."""

    item_count: int
    resume_cursor: PromptHistoryPageCursor | None


def _display_text_for_item(item: _PromptDisplayItem) -> str:
    """Return the humanized prompt text for display and user-facing actions."""
    return item.display_text if item.display_text is not None else item.entry.text


def _create_prompt_history_label(
    item: _PromptDisplayItem,
    *,
    preview_width: int = _FALLBACK_PREVIEW_WIDTH,
) -> Text:
    """Create a single-line styled label for a prompt history item."""
    return _render_prompt_history_label(
        item,
        preview_width=preview_width,
        summarize_for_list=summarize_prompt_for_list,
    )


class PromptHistoryModal(
    OptionListNavigationMixin, ModalScreen[PromptHistoryResult | None]
):
    """Modal for selecting a prompt from history with filtering and preview."""

    _option_list_id = "prompt-history-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("ctrl+j", "load_more", "Load More", priority=True),
        Binding("ctrl+k", "unload", "Unload", priority=True),
        ("ctrl+g", "edit_first", "Edit in editor"),
        ("ctrl+x", "toggle_cancelled", "Toggle cancelled"),
        ("ctrl+y", "copy_and_cancel", "Copy & cancel"),
    ]

    def __init__(
        self,
        show_cancelled: bool = False,
        initial_filter: str = "",
    ) -> None:
        """Initialize the prompt history modal.

        Args:
            show_cancelled: Whether to show cancelled prompts by default.
            initial_filter: Text to pre-fill in the modal filter.
        """
        super().__init__()
        self._all_items: list[_PromptDisplayItem] = []
        self._filtered_items: list[_PromptDisplayItem] = []
        self._show_cancelled = show_cancelled
        self._initial_filter = initial_filter
        self._last_preview_width_budget = _FALLBACK_PREVIEW_WIDTH
        self._next_cursor: PromptHistoryPageCursor | None = None
        self._history_exhausted = False
        self._history_loaded_once = False
        self._history_loading = False
        self._page_size = get_ace_page_size()
        self._loaded_pages: list[_PromptHistoryLoadedPage] = []
        self._filtered_items = []

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
        for record in page.records:
            entry = record.to_entry()
            self._all_items.append(
                _PromptDisplayItem(
                    entry=entry,
                    marker="x" if entry.cancelled else " ",
                    display_text=humanize_vcs_refs_in_text(entry.text),
                )
            )
        if not hasattr(self, "_loaded_pages"):
            self._loaded_pages = []
        self._loaded_pages.append(
            _PromptHistoryLoadedPage(
                item_count=len(page.records),
                resume_cursor=resume_cursor,
            )
        )
        self._next_cursor = page.next_cursor
        self._history_exhausted = page.exhausted
        self._history_loaded_once = True

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="prompt-history-modal-container"):
            yield Label("Select Prompt from History", id="modal-title")
            yield FilterInput(
                value=self._initial_filter,
                placeholder="Type to filter loaded prompts...",
                id="prompt-history-filter-input",
            )
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
            yield Static(
                self._hints_text(),
                id="prompt-history-hints",
            )

    def _hints_text(self) -> str:
        """Return the footer hint line using the configured page size."""
        page_size = self._resolved_page_size()
        return (
            f"j/k ^n/^p • ^j/+{page_size} ^k/-{page_size} • Enter: submit • "
            "^g: edit • ^i: load • ^x: cancelled • ^y: copy • Esc/q: cancel"
        )

    def _create_styled_label(self, item: _PromptDisplayItem) -> Text:
        """Create styled text for a prompt list item."""
        return _create_prompt_history_label(
            item,
            preview_width=self._last_preview_width_budget,
        )

    def _create_initial_options(self) -> list[Option]:
        """Return initial rows, including a loading row before disk data lands."""
        options = self._create_options(self._filtered_items)
        if options or self._history_loaded_once:
            return options
        return [self._loading_option()]

    @staticmethod
    def _loading_option() -> Option:
        """Return the disabled placeholder shown during the initial page load."""
        return Option(Text("Loading prompt history...", style="dim"), disabled=True)

    def _create_options(
        self,
        items: list[_PromptDisplayItem],
        *,
        preview_width: int | None = None,
    ) -> list[Option]:
        """Create options from prompt items."""
        self._last_preview_width_budget = (
            self._resolve_preview_width_budget()
            if preview_width is None
            else preview_width
        )
        return [
            Option(self._create_styled_label(item), id=str(i))
            for i, item in enumerate(items)
        ]

    def _resolve_preview_width_budget(self) -> int:
        """Return the current prompt preview width budget for list rows."""
        try:
            option_list = self.query_one("#prompt-history-list", OptionList)
        except Exception:
            return _FALLBACK_PREVIEW_WIDTH

        list_content_width = option_list.scrollable_content_region.width
        if list_content_width <= 0:
            list_content_width = option_list.content_size.width
        if list_content_width <= 0:
            list_content_width = option_list.size.width
        return _prompt_preview_width_for_list_content(list_content_width)

    def _refresh_options(
        self,
        *,
        preserve_highlight: bool = False,
        preview_width: int | None = None,
    ) -> None:
        """Rebuild visible options using one shared preview-width budget."""
        option_list = self.query_one("#prompt-history-list", OptionList)
        highlighted = option_list.highlighted if preserve_highlight else None
        option_list.clear_options()
        option_list.add_options(
            self._create_options(
                self._filtered_items,
                preview_width=preview_width,
            )
        )
        if not self._filtered_items:
            if not self._history_loaded_once:
                option_list.add_option(self._loading_option())
            return
        if preserve_highlight and highlighted is not None:
            option_list.highlighted = min(highlighted, len(self._filtered_items) - 1)
        elif not preserve_highlight:
            option_list.highlighted = 0

    def _refresh_options_for_current_width(self) -> None:
        """Refresh option labels if layout gives the preview column a new width."""
        if not self._all_items:
            return
        preview_width = self._resolve_preview_width_budget()
        if preview_width == self._last_preview_width_budget:
            return
        self._refresh_options(preserve_highlight=True, preview_width=preview_width)

    def _history_count_label(self) -> str:
        """Return the live list-pane history count label."""
        history_loading = getattr(self, "_history_loading", False)
        history_loaded_once = getattr(self, "_history_loaded_once", True)
        history_exhausted = getattr(self, "_history_exhausted", True)
        if history_loading and not history_loaded_once:
            return "History · loading..."
        loaded = len(self._all_items)
        visible = len(self._filtered_items)
        if not history_loaded_once:
            return "History · loading..."
        if history_exhausted:
            return f"History · {visible:,} / {loaded:,} total"
        suffix = f" · ^j +{self._resolved_page_size()} older"
        if history_loading:
            suffix = " · loading older..."
        return f"History · {visible:,} / {loaded:,} loaded{suffix}"

    def _update_history_count_label(self) -> None:
        """Update the list-pane count label if it is mounted."""
        try:
            label = self.query_one("#prompt-history-list-label", Label)
        except Exception:
            return
        label.update(self._history_count_label())

    def _get_filtered_items(self, filter_text: str) -> list[_PromptDisplayItem]:
        """Get items that match the filter text."""
        if not filter_text:
            if self._show_cancelled:
                return self._all_items.copy()
            return [item for item in self._all_items if not item.entry.cancelled]

        filter_lower = filter_text.lower()
        return [
            item
            for item in self._all_items
            if (self._show_cancelled or not item.entry.cancelled)
            and (
                filter_lower in _display_text_for_item(item).lower()
                or filter_lower in item.entry.text.lower()
            )
        ]

    def _get_selected_prompt_text(self) -> str | None:
        """Get the prompt text for the currently highlighted item."""
        if not self._filtered_items:
            return None
        option_list = self.query_one("#prompt-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_items):
            return _display_text_for_item(self._filtered_items[highlighted])
        return _display_text_for_item(self._filtered_items[0])

    def on_key(self, event: events.Key) -> None:
        """Intercept keys that focused widgets consume before bindings.

        - Tab/Ctrl+I: Textual's focus cycling intercepts Tab before bindings.
        - Ctrl+J / Ctrl+K: intercepted while the filter input is focused so
          the keys page history here instead of bubbling to the app-level
          metadata-section bindings.
        - Ctrl+X: Input widget's built-in "cut" binding consumes it.
        """
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.action_load_to_input()
        elif event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.action_load_more()
        elif event.key == "ctrl+k":
            event.prevent_default()
            event.stop()
            self.action_unload()
        elif event.key == "ctrl+x":
            event.prevent_default()
            event.stop()
            self.action_toggle_cancelled()

    def on_mount(self) -> None:
        """Focus immediately and load the initial page outside the modal pump."""
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        filter_input.focus()
        filter_input.cursor_position = len(filter_input.value)
        self.run_worker(
            self._load_more_async(preserve_highlight=False),
            exclusive=True,
            group="prompt-history-load",
        )

    def on_resize(self, _event: events.Resize) -> None:
        """Recompute adaptive row widths after terminal resize/layout changes."""
        if self._all_items:
            self.call_after_refresh(self._refresh_options_for_current_width)

    async def _load_more_async(self, *, preserve_highlight: bool = True) -> None:
        """Load another bounded prompt-history page off the event loop."""
        if self._history_loading or self._history_exhausted:
            return
        self._history_loading = True
        self._update_history_count_label()
        try:
            page = await asyncio.to_thread(self._load_page)
        except Exception as exc:
            self.notify(f"Failed to load prompt history: {exc}", severity="error")
            return
        finally:
            self._history_loading = False

        self._append_page(page)
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        self._filtered_items = self._get_filtered_items(filter_input.value)
        self._update_history_count_label()
        self._refresh_options(preserve_highlight=preserve_highlight)
        if self._filtered_items:
            option_list = self.query_one("#prompt-history-list", OptionList)
            highlighted = option_list.highlighted
            idx = highlighted if highlighted is not None else 0
            idx = min(max(idx, 0), len(self._filtered_items) - 1)
            option_list.highlighted = idx
            self._update_preview(self._filtered_items[idx])
            self.call_after_refresh(self._refresh_options_for_current_width)
        else:
            self._clear_preview()

    def action_load_more(self) -> None:
        """Load the next prompt-history page."""
        if self._history_loading or self._history_exhausted:
            self._update_history_count_label()
            return
        self.run_worker(
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
        self._next_cursor = last.resume_cursor
        self._history_exhausted = False
        try:
            filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
            filter_text = filter_input.value
        except Exception:
            filter_text = ""
        self._filtered_items = self._get_filtered_items(filter_text)
        self._update_history_count_label()
        try:
            self._refresh_options(preserve_highlight=True)
        except Exception:
            return
        if self._filtered_items:
            option_list = self.query_one("#prompt-history-list", OptionList)
            highlighted = option_list.highlighted
            idx = highlighted if highlighted is not None else 0
            idx = min(max(idx, 0), len(self._filtered_items) - 1)
            option_list.highlighted = idx
            self._update_preview(self._filtered_items[idx])
        else:
            self._clear_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        self._filtered_items = self._get_filtered_items(event.value)
        self._update_history_count_label()
        self._refresh_options()
        # Update preview for first filtered item
        if self._filtered_items:
            self._update_preview(self._filtered_items[0])
        else:
            self._clear_preview()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Handle Enter key in input - select and submit directly."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.SUBMIT,
                    prompt_text=prompt_text,
                )
            )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update preview when highlighting changes."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._filtered_items):
                self._update_preview(self._filtered_items[idx])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (click/double-click) - submit directly."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._filtered_items):
                self.dismiss(
                    PromptHistoryResult(
                        action=PromptHistoryAction.SUBMIT,
                        prompt_text=_display_text_for_item(self._filtered_items[idx]),
                    )
                )

    def action_edit_first(self) -> None:
        """Handle Ctrl+G - select and open in editor first."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.EDIT_FIRST,
                    prompt_text=prompt_text,
                )
            )

    def action_toggle_cancelled(self) -> None:
        """Handle Ctrl+X - toggle visibility of cancelled prompts."""
        self._show_cancelled = not self._show_cancelled
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        self._filtered_items = self._get_filtered_items(filter_input.value)
        self._update_history_count_label()
        self._refresh_options()
        if self._filtered_items:
            self._update_preview(self._filtered_items[0])
        else:
            self._clear_preview()

    def action_load_to_input(self) -> None:
        """Handle Ctrl+I - load selected prompt into prompt input widget."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.LOAD,
                    prompt_text=prompt_text,
                )
            )

    def action_copy_and_cancel(self) -> None:
        """Handle Ctrl+Y - copy selected prompt to clipboard and dismiss."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            from sase.ace.tui.actions.clipboard import schedule_copy_delivery

            schedule_copy_delivery(
                self.app,
                prompt_text,
                copied_label="prompt",
                task_name="sase-copy-prompt-history",
            )
        self.dismiss(None)

    def _update_preview(self, item: _PromptDisplayItem) -> None:
        """Update preview panel with full prompt and metadata."""
        try:
            preview = self.query_one("#prompt-history-preview", Static)
            metadata = self.query_one("#prompt-history-metadata", Static)

            preview.update(_display_text_for_item(item))
            metadata.update(
                build_prompt_history_metadata(
                    item,
                    summarize_for_preview=summarize_prompt_for_preview,
                )
            )

        except Exception:
            pass

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            preview = self.query_one("#prompt-history-preview", Static)
            metadata = self.query_one("#prompt-history-metadata", Static)
            preview.update("")
            metadata.update("")
        except Exception:
            pass
