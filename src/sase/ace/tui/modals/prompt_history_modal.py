"""Prompt history selection modal with filtering for the ace TUI."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from sase.history.prompt import (
    PromptEntry,
    PromptHistoryPage,
    PromptHistoryPageCursor,
    load_prompt_record_page,
)
from sase.history.prompt_metadata import (
    PromptListSummary,
    PromptPreviewSummary,
    summarize_prompt_for_list,
    summarize_prompt_for_preview,
)
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin

_LAST_USED_WIDTH = 11
_MARKER_COL_WIDTH = 2
_PROJECT_COL_WIDTH = 14
_TAGS_COL_WIDTH = 16
_COLUMN_GAP_WIDTH = 2
_OPTION_HORIZONTAL_PADDING_WIDTH = 2
_MIN_PREVIEW_WIDTH = 16
_FALLBACK_PREVIEW_WIDTH = 132
_PROMPT_HISTORY_PAGE_SIZE = 250
_PROMPT_COL_START = (
    _MARKER_COL_WIDTH
    + _LAST_USED_WIDTH
    + _COLUMN_GAP_WIDTH
    + _PROJECT_COL_WIDTH
    + _COLUMN_GAP_WIDTH
    + _TAGS_COL_WIDTH
    + _COLUMN_GAP_WIDTH
)
_PROJECT_PLACEHOLDER = "—"


class PromptHistoryAction(Enum):
    """Action type for prompt history modal result."""

    SUBMIT = auto()  # Enter - submit prompt directly
    EDIT_FIRST = auto()  # Ctrl+G - open in editor first
    LOAD = auto()  # Ctrl+I - load into prompt input widget


@dataclass
class PromptHistoryResult:
    """Result from PromptHistoryModal."""

    action: PromptHistoryAction
    prompt_text: str


@dataclass
class _PromptDisplayItem:
    """Wrapper for prompt entry with display info."""

    entry: PromptEntry
    marker: str  # " " or "x"
    summary: PromptListSummary | None = None


def _ellipsize_right(value: str, width: int) -> str:
    """Trim text to width, reserving space for an ellipsis when possible."""
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return "." * width
    return f"{value[: width - 3]}..."


def _format_history_timestamp(timestamp: str) -> str:
    """Format SASE history timestamps as compact MM-DD HH:MM values."""
    raw_timestamp = timestamp.strip()
    try:
        return datetime.strptime(raw_timestamp, "%y%m%d_%H%M%S").strftime("%m-%d %H:%M")
    except ValueError:
        return raw_timestamp[:_LAST_USED_WIDTH].ljust(_LAST_USED_WIDTH)


def _prompt_history_header_text() -> Text:
    """Return the fixed-column header aligned with prompt-history rows."""
    text = Text(no_wrap=True, overflow="crop", style="bold dim")
    text.append(" " * _MARKER_COL_WIDTH)
    text.append(f"{'WHEN':<{_LAST_USED_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append(f"{'PROJECT':<{_PROJECT_COL_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append(f"{'TAGS':<{_TAGS_COL_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append("PROMPT")
    return text


def _prompt_preview_width_for_list_content(list_content_width: int) -> int:
    """Return prompt-preview column width from the laid-out list content width."""
    if list_content_width <= 0:
        return _FALLBACK_PREVIEW_WIDTH
    text_width = list_content_width - _OPTION_HORIZONTAL_PADDING_WIDTH
    return max(_MIN_PREVIEW_WIDTH, text_width - _PROMPT_COL_START)


def _create_prompt_history_label(
    item: _PromptDisplayItem,
    *,
    preview_width: int = _FALLBACK_PREVIEW_WIDTH,
) -> Text:
    """Create a single-line styled label for a prompt history item."""
    text = Text(no_wrap=True, overflow="ellipsis")
    is_cancelled = item.entry.cancelled or item.marker == "x"
    summary = _get_prompt_list_summary(item)

    if is_cancelled:
        text.append("x ", style="magenta")
    else:
        text.append("  ")

    metadata_style = "dim italic" if is_cancelled else "dim"
    prompt_style = "dim italic" if is_cancelled else ""
    project_ref_style = "dim italic" if is_cancelled else "cyan"
    xprompt_style = "dim italic" if is_cancelled else "green"
    directive_style = "dim italic" if is_cancelled else "yellow"

    last_used = _format_history_timestamp(item.entry.last_used)
    prompt = _ellipsize_right(
        summary.clean_preview,
        preview_width,
    )

    text.append(last_used, style=metadata_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    _append_project_column(text, summary, metadata_style, project_ref_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    _append_tag_columns(text, summary, xprompt_style, directive_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    text.append(prompt, style=prompt_style)

    return text


def _get_prompt_list_summary(item: _PromptDisplayItem) -> PromptListSummary:
    """Return a cached list summary for a prompt display item."""
    if item.summary is None:
        item.summary = summarize_prompt_for_list(item.entry.text)
    return item.summary


def _append_project_column(
    text: Text,
    summary: PromptListSummary,
    metadata_style: str,
    project_ref_style: str,
) -> None:
    """Append the fixed-width project column to a history row."""
    if not summary.project_prefix and not summary.project_ref_display:
        text.append(_PROJECT_PLACEHOLDER, style=metadata_style)
        text.append(" " * (_PROJECT_COL_WIDTH - len(_PROJECT_PLACEHOLDER)))
        return

    prefix = summary.project_prefix
    ref_width = max(_PROJECT_COL_WIDTH - len(prefix), 0)
    ref = _ellipsize_right(summary.project_ref_display, ref_width)
    if not ref and len(prefix) > _PROJECT_COL_WIDTH:
        prefix = _ellipsize_right(prefix, _PROJECT_COL_WIDTH)

    text.append(prefix, style=metadata_style)
    if ref:
        text.append(ref, style=project_ref_style)

    padding = _PROJECT_COL_WIDTH - len(prefix) - len(ref)
    if padding > 0:
        text.append(" " * padding)


def _append_tag_columns(
    text: Text,
    summary: PromptListSummary,
    xprompt_style: str,
    directive_style: str,
) -> None:
    """Append the fixed-width xprompt/directive tag column."""
    tokens = [(chip, xprompt_style) for chip in summary.xprompts]
    if summary.directive_token:
        tokens.append((summary.directive_token, directive_style))

    rendered = _fit_tag_tokens(tokens, _TAGS_COL_WIDTH)
    used = _append_tag_tokens(text, rendered)
    padding = _TAGS_COL_WIDTH - used
    if padding > 0:
        text.append(" " * padding)


def _fit_tag_tokens(
    tokens: list[tuple[str, str]],
    width: int,
) -> list[tuple[str, str]]:
    """Fit styled tag tokens into a fixed-width list column."""
    if width <= 0 or not tokens:
        return []

    displayed: list[tuple[str, str]] = []
    hidden_count = 0
    for index, styled_token in enumerate(tokens):
        candidate = [*displayed, styled_token]
        if _tag_tokens_width(candidate) <= width:
            displayed = candidate
            continue
        hidden_count = len(tokens) - index
        break

    if hidden_count == 0:
        return displayed

    if not displayed:
        token_text, style = tokens[0]
        if len(tokens) == 1:
            return [(_ellipsize_right(token_text, width), style)]
        suffix = f"+{len(tokens)}"
        return [(_ellipsize_right(suffix, width), style)]

    overflow_style = displayed[-1][1]
    while displayed:
        suffix = f"+{hidden_count}" if hidden_count > 1 else "..."
        candidate = [*displayed, (suffix, overflow_style)]
        if _tag_tokens_width(candidate) <= width:
            return candidate
        displayed.pop()
        hidden_count += 1
        overflow_style = displayed[-1][1] if displayed else tokens[0][1]

    suffix = f"+{len(tokens)}"
    return [(_ellipsize_right(suffix, width), tokens[0][1])]


def _tag_tokens_width(tokens: list[tuple[str, str]]) -> int:
    """Return plain-text width for space-separated tag tokens."""
    if not tokens:
        return 0
    return sum(len(token) for token, _style in tokens) + len(tokens) - 1


def _append_tag_tokens(text: Text, tokens: list[tuple[str, str]]) -> int:
    """Append fitted tag tokens and return their plain-text width."""
    used = 0
    for index, (token, style) in enumerate(tokens):
        if index:
            text.append(" ")
            used += 1
        text.append(token, style=style)
        used += len(token)
    return used


def _append_metadata_row(
    meta_text: Text,
    label: str,
    value: str,
    *,
    value_style: str | None = None,
) -> None:
    """Append one aligned metadata row."""
    meta_text.append(f"{label + ':':<12}", style="bold")
    meta_text.append(f"{value}\n", style=value_style)


def _preview_project_value(summary: PromptPreviewSummary) -> str:
    """Return the preview metadata value for a prompt project."""
    return summary.vcs_tag.strip() if summary.vcs_tag else _PROJECT_PLACEHOLDER


class PromptHistoryModal(
    OptionListNavigationMixin, ModalScreen[PromptHistoryResult | None]
):
    """Modal for selecting a prompt from history with filtering and preview."""

    _option_list_id = "prompt-history-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("pagedown", "load_more", "Load More", priority=True),
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
        self._filtered_items = []

    def _load_page(self) -> PromptHistoryPage:
        """Load the next page of prompt history records."""
        return load_prompt_record_page(
            page_size=_PROMPT_HISTORY_PAGE_SIZE,
            cursor=self._next_cursor,
            include_cancelled=True,
        )

    def _append_page(self, page: PromptHistoryPage) -> None:
        """Append a loaded page to modal state."""
        for record in page.records:
            entry = record.to_entry()
            self._all_items.append(
                _PromptDisplayItem(
                    entry=entry,
                    marker="x" if entry.cancelled else " ",
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
                            *self._create_options(self._filtered_items),
                            id="prompt-history-list",
                        )
                with Vertical(id="prompt-history-preview-panel"):
                    yield Label("Preview", id="prompt-history-preview-label")
                    with VerticalScroll(id="prompt-history-preview-scroll"):
                        yield Static("", id="prompt-history-preview", markup=False)
                        yield Static("", id="prompt-history-metadata")
            yield Static(
                "j/k ↑/↓ ^n/^p: navigate • PgDn: older +250 • Enter: submit • ^g: edit • ^i: load • ^x: cancelled • ^y: copy • Esc/q: cancel",
                id="prompt-history-hints",
            )

    def _create_styled_label(self, item: _PromptDisplayItem) -> Text:
        """Create styled text for a prompt list item."""
        return _create_prompt_history_label(
            item,
            preview_width=self._last_preview_width_budget,
        )

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
        suffix = " · PgDn +250 older"
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
            and filter_lower in item.entry.text.lower()
        ]

    def _get_selected_prompt_text(self) -> str | None:
        """Get the prompt text for the currently highlighted item."""
        if not self._filtered_items:
            return None
        option_list = self.query_one("#prompt-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_items):
            return self._filtered_items[highlighted].entry.text
        return self._filtered_items[0].entry.text

    def on_key(self, event: events.Key) -> None:
        """Intercept keys that focused widgets consume before bindings.

        - Tab/Ctrl+I: Textual's focus cycling intercepts Tab before bindings.
        - Ctrl+X: Input widget's built-in "cut" binding consumes it.
        """
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.action_load_to_input()
        elif event.key == "ctrl+x":
            event.prevent_default()
            event.stop()
            self.action_toggle_cancelled()

    async def on_mount(self) -> None:
        """Focus the input and show initial preview on mount."""
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        filter_input.focus()
        filter_input.cursor_position = len(filter_input.value)
        await self._load_more_async(preserve_highlight=False)

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
        self.run_worker(self._load_more_async(), exclusive=True)

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
                        prompt_text=self._filtered_items[idx].entry.text,
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
            from sase.ace.tui.actions.clipboard import copy_to_system_clipboard

            if copy_to_system_clipboard(prompt_text):
                self.app.notify("Copied prompt to clipboard")
            else:
                self.app.notify("Failed to copy to clipboard", severity="error")
        self.dismiss(None)

    def _update_preview(self, item: _PromptDisplayItem) -> None:
        """Update preview panel with full prompt and metadata."""
        try:
            preview = self.query_one("#prompt-history-preview", Static)
            metadata = self.query_one("#prompt-history-metadata", Static)

            # Full prompt text
            preview.update(item.entry.text)

            # Metadata section
            summary = summarize_prompt_for_preview(item.entry.text)
            meta_text = Text()
            meta_text.append("\n--- Metadata ---\n", style="dim")
            if item.entry.cancelled:
                _append_metadata_row(
                    meta_text,
                    "Status",
                    "Cancelled",
                    value_style="magenta",
                )
            _append_metadata_row(
                meta_text,
                "Project",
                _preview_project_value(summary),
            )
            if summary.xprompts:
                _append_metadata_row(
                    meta_text,
                    "Workflows",
                    ", ".join(summary.xprompts),
                    value_style="green",
                )
            if summary.directives:
                _append_metadata_row(
                    meta_text,
                    "Directives",
                    ", ".join(summary.directives),
                    value_style="yellow",
                )
            _append_metadata_row(meta_text, "Created", item.entry.timestamp)
            _append_metadata_row(meta_text, "Last Used", item.entry.last_used)
            metadata.update(meta_text)

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
