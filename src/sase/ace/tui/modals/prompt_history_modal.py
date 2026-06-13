"""Prompt history selection modal with filtering for the ace TUI."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from sase.history.prompt import PromptEntry, get_prompts_for_fzf
from sase.history.prompt_metadata import (
    PromptListSummary,
    PromptPreviewSummary,
    summarize_prompt_for_list,
    summarize_prompt_for_preview,
)
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin

_LAST_USED_WIDTH = 11
_PROMPT_PREVIEW_WIDTH = 96
_PROJECT_COL_WIDTH = 12
_MAX_TAG_CHIPS = 3
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


def _create_prompt_history_label(item: _PromptDisplayItem) -> Text:
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
        _PROMPT_PREVIEW_WIDTH,
    )

    text.append(last_used, style=metadata_style)
    text.append("  ", style="dim")
    _append_project_column(text, summary, metadata_style, project_ref_style)
    text.append("  ", style="dim")
    _append_tag_columns(text, summary, xprompt_style, directive_style)
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
    """Append xprompt and directive chips before the cleaned preview."""
    has_tag = False
    xprompts = list(summary.xprompts[:_MAX_TAG_CHIPS])
    overflow = len(summary.xprompts) - len(xprompts)

    for chip in xprompts:
        if has_tag:
            text.append(" ")
        text.append(chip, style=xprompt_style)
        has_tag = True

    if overflow > 0:
        if has_tag:
            text.append(" ")
        text.append(f"+{overflow}", style=xprompt_style)
        has_tag = True

    if summary.directive_token:
        if has_tag:
            text.append(" ")
        text.append(summary.directive_token, style=directive_style)
        has_tag = True

    if has_tag:
        text.append("  ")


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
        self._load_items()
        self._filtered_items = self._get_filtered_items(self._initial_filter)

    def _load_items(self) -> None:
        """Load prompt history items (including cancelled for toggle filtering)."""
        items = get_prompts_for_fzf(include_cancelled=True)

        if not items:
            return

        for _display_str, entry in items:
            if entry.cancelled:
                marker = "x"
            else:
                marker = " "

            self._all_items.append(
                _PromptDisplayItem(
                    entry=entry,
                    marker=marker,
                )
            )

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="prompt-history-modal-container"):
            yield Label("Select Prompt from History", id="modal-title")
            if not self._all_items:
                yield Label("No prompt history found.")
            else:
                yield FilterInput(
                    value=self._initial_filter,
                    placeholder="Type to filter...",
                    id="prompt-history-filter-input",
                )
                with Horizontal(id="prompt-history-panels"):
                    with Vertical(id="prompt-history-list-panel"):
                        yield Label("History", id="prompt-history-list-label")
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
                    "j/k ↑/↓ ^n/^p: navigate • Enter: submit • ^g: edit • ^i: load • ^x: cancelled • ^y: copy • Esc/q: cancel",
                    id="prompt-history-hints",
                )

    def _create_styled_label(self, item: _PromptDisplayItem) -> Text:
        """Create styled text for a prompt list item."""
        return _create_prompt_history_label(item)

    def _create_options(self, items: list[_PromptDisplayItem]) -> list[Option]:
        """Create options from prompt items."""
        return [
            Option(self._create_styled_label(item), id=str(i))
            for i, item in enumerate(items)
        ]

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

    def on_mount(self) -> None:
        """Focus the input and show initial preview on mount."""
        if self._all_items:
            filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
            filter_input.focus()
            filter_input.cursor_position = len(filter_input.value)
            # Show preview for first item
            if self._filtered_items:
                self._update_preview(self._filtered_items[0])

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        self._filtered_items = self._get_filtered_items(event.value)
        option_list = self.query_one("#prompt-history-list", OptionList)
        option_list.clear_options()
        for option in self._create_options(self._filtered_items):
            option_list.add_option(option)
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
        option_list = self.query_one("#prompt-history-list", OptionList)
        option_list.clear_options()
        for option in self._create_options(self._filtered_items):
            option_list.add_option(option)
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
