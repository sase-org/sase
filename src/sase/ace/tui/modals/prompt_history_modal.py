"""Prompt history selection modal with filtering for the ace TUI."""

from dataclasses import dataclass
from enum import Enum, auto

from sase.prompt_history import PromptEntry, get_prompts_for_fzf
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin


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
    marker: str  # "*", "~", " ", or "✗"
    display_branch: str  # Padded branch name


class PromptHistoryModal(
    OptionListNavigationMixin, ModalScreen[PromptHistoryResult | None]
):
    """Modal for selecting a prompt from history with filtering and preview."""

    _option_list_id = "prompt-history-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("ctrl+g", "edit_first", "Edit in editor"),
        ("ctrl+i", "load_to_input", "Load to input"),
        ("ctrl+y", "copy_and_cancel", "Copy & cancel"),
    ]

    def __init__(
        self,
        sort_by: str | None = None,
        workspace: str | None = None,
    ) -> None:
        """Initialize the prompt history modal.

        Args:
            sort_by: Branch/CL name to prioritize in sorting.
            workspace: Workspace/project name for secondary sorting.
        """
        super().__init__()
        self._sort_by = sort_by
        self._workspace = workspace
        self._all_items: list[_PromptDisplayItem] = []
        self._filtered_items: list[_PromptDisplayItem] = []
        self._load_items()

    def _load_items(self) -> None:
        """Load prompt history items (including cancelled for @ filtering)."""
        items = get_prompts_for_fzf(
            current_branch=self._sort_by,
            current_workspace=self._workspace,
            include_cancelled=True,
        )

        if not items:
            return

        # Calculate max branch length for alignment
        max_branch_len = max(len(entry.branch_or_workspace) for _, entry in items)

        for display_str, entry in items:
            if entry.cancelled:
                marker = "✗"
            else:
                # Parse marker from display string (first char)
                marker = display_str[0] if display_str else " "
            display_branch = entry.branch_or_workspace.ljust(max_branch_len)

            self._all_items.append(
                _PromptDisplayItem(
                    entry=entry,
                    marker=marker,
                    display_branch=display_branch,
                )
            )

        # Default view: only non-cancelled items
        self._filtered_items = [
            item for item in self._all_items if not item.entry.cancelled
        ]

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="prompt-history-modal-container"):
            yield Label("Select Prompt from History", id="modal-title")
            if not self._all_items:
                yield Label("No prompt history found.")
            else:
                # Header showing sort context
                header_text = self._get_header_text()
                yield Static(header_text, id="prompt-history-header")

                yield FilterInput(
                    placeholder='Type to filter ("@ " to include cancelled)...',
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
                    "j/k ↑/↓ ^n/^p: navigate • Enter: submit • ^g: edit • ^i: load • ^y: copy • Esc/q: cancel",
                    id="prompt-history-hints",
                )

    def _get_header_text(self, include_cancelled: bool = False) -> Text:
        """Get header text showing sort context."""
        text = Text()
        if self._sort_by and self._workspace:
            text.append("* ", style="bold green")
            text.append(f"= {self._sort_by}  ")
            text.append("~ ", style="bold yellow")
            text.append(f"= {self._workspace}")
        elif self._sort_by:
            text.append("* ", style="bold green")
            text.append(f"= {self._sort_by}")
        else:
            text.append("* ", style="bold green")
            text.append("= current branch")
        if include_cancelled:
            text.append("  ")
            text.append("✗ ", style="magenta")
            text.append("= cancelled")
        return text

    def _create_styled_label(self, item: _PromptDisplayItem) -> Text:
        """Create styled text for a prompt list item."""
        text = Text()
        is_cancelled = item.marker == "✗"

        # Color-coded marker
        if is_cancelled:
            text.append("✗ ", style="magenta")
        elif item.marker == "*":
            text.append("* ", style="bold green")
        elif item.marker == "~":
            text.append("~ ", style="bold yellow")
        else:
            text.append("  ")

        # Branch/workspace name
        branch_style = "dim" if is_cancelled else "dim cyan"
        text.append(item.display_branch, style=branch_style)
        text.append(" | ", style="dim")

        # Truncated prompt preview
        preview = item.entry.text.replace("\n", " ").replace("\r", " ")
        if len(preview) > 40:
            preview = preview[:40] + "..."
        preview_style = "dim italic" if is_cancelled else ""
        text.append(preview, style=preview_style)

        return text

    def _create_options(self, items: list[_PromptDisplayItem]) -> list[Option]:
        """Create options from prompt items."""
        return [
            Option(self._create_styled_label(item), id=str(i))
            for i, item in enumerate(items)
        ]

    def _get_filtered_items(self, filter_text: str) -> list[_PromptDisplayItem]:
        """Get items that match the filter text.

        When filter_text starts with "@ ", cancelled prompts are included
        and the search query is the text after "@ ".
        """
        include_cancelled = filter_text.startswith("@ ")
        if include_cancelled:
            filter_text = filter_text[2:]

        if not filter_text:
            if include_cancelled:
                return self._all_items.copy()
            return [item for item in self._all_items if not item.entry.cancelled]

        filter_lower = filter_text.lower()
        return [
            item
            for item in self._all_items
            if (include_cancelled or not item.entry.cancelled)
            and (
                filter_lower in item.entry.text.lower()
                or filter_lower in item.entry.branch_or_workspace.lower()
            )
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

    def on_mount(self) -> None:
        """Focus the input and show initial preview on mount."""
        if self._all_items:
            filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
            filter_input.focus()
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
        # Update header to show/hide cancelled legend
        self._update_header(include_cancelled=event.value.startswith("@ "))

    def _update_header(self, include_cancelled: bool = False) -> None:
        """Update the header to reflect current filter mode."""
        try:
            header = self.query_one("#prompt-history-header", Static)
            header.update(self._get_header_text(include_cancelled))
        except Exception:
            pass

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
            meta_text = Text()
            meta_text.append("\n--- Metadata ---\n", style="dim")
            if item.entry.cancelled:
                meta_text.append("Status: ", style="bold")
                meta_text.append("Cancelled\n", style="magenta")
            meta_text.append("Branch: ", style="bold")
            meta_text.append(f"{item.entry.branch_or_workspace}\n")
            if item.entry.workspace:
                meta_text.append("Workspace: ", style="bold")
                meta_text.append(f"{item.entry.workspace}\n")
            meta_text.append("Created: ", style="bold")
            meta_text.append(f"{item.entry.timestamp}\n")
            meta_text.append("Last Used: ", style="bold")
            meta_text.append(f"{item.entry.last_used}\n")
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
