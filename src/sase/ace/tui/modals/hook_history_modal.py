"""Hook history selection modal with filtering for the ace TUI."""

from dataclasses import dataclass
from enum import Enum, auto

from sase.history.hook import HookHistoryEntry, delete_hook, get_hooks_for_display
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin


class HookHistoryAction(Enum):
    """Action type for hook history modal result."""

    SUBMIT = auto()  # Enter - submit hook directly
    EDIT_FIRST = auto()  # Ctrl+G - open in hooks input bar first


@dataclass
class HookHistoryResult:
    """Result from HookHistoryModal."""

    action: HookHistoryAction
    command: str


class HookHistoryModal(
    OptionListNavigationMixin, ModalScreen[HookHistoryResult | None]
):
    """Modal for selecting a hook from history with filtering."""

    _option_list_id = "hook-history-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("ctrl+d", "delete_hook", "Delete hook", priority=True),
        Binding("ctrl+g", "edit_first", "Edit first", priority=True),
    ]

    def __init__(self) -> None:
        """Initialize the hook history modal."""
        super().__init__()
        self._all_items: list[HookHistoryEntry] = []
        self._filtered_items: list[HookHistoryEntry] = []
        self._load_items()

    def _load_items(self) -> None:
        """Load hook history items."""
        self._all_items = get_hooks_for_display()
        self._filtered_items = self._all_items.copy()

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="hook-history-modal-container"):
            yield Label("Hook History", id="modal-title")
            yield FilterInput(
                placeholder="Type to filter hooks...",
                id="hook-history-filter-input",
            )
            with Vertical(id="hook-history-list-panel"):
                yield Label("History", id="hook-history-list-label")
                yield OptionList(
                    *self._create_options(self._filtered_items),
                    id="hook-history-list",
                )
            yield Static(
                "j/k ^n/^p: navigate | Enter: select | ^d: delete | ^g: edit | Esc/q: cancel",
                id="hook-history-hints",
            )

    def _create_styled_label(self, entry: HookHistoryEntry) -> Text:
        """Create styled text for a hook list item."""
        text = Text()
        text.append(entry.command)
        text.append(f"  ({entry.last_used})", style="dim")
        return text

    def _create_options(self, items: list[HookHistoryEntry]) -> list[Option]:
        """Create options from hook items."""
        return [
            Option(self._create_styled_label(item), id=str(i))
            for i, item in enumerate(items)
        ]

    def _get_filtered_items(self, filter_text: str) -> list[HookHistoryEntry]:
        """Get items that match the filter text."""
        if not filter_text:
            return self._all_items.copy()

        filter_lower = filter_text.lower()
        return [
            item for item in self._all_items if filter_lower in item.command.lower()
        ]

    def _get_selected_command(self) -> str | None:
        """Get the command text for the currently highlighted item."""
        if not self._filtered_items:
            return None
        option_list = self.query_one("#hook-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_items):
            return self._filtered_items[highlighted].command
        return self._filtered_items[0].command

    def on_mount(self) -> None:
        """Focus the input on mount."""
        filter_input = self.query_one("#hook-history-filter-input", FilterInput)
        filter_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        self._filtered_items = self._get_filtered_items(event.value)
        option_list = self.query_one("#hook-history-list", OptionList)
        option_list.clear_options()
        for option in self._create_options(self._filtered_items):
            option_list.add_option(option)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key - submit selected hook."""
        if self._filtered_items:
            command = self._get_selected_command()
            if command:
                self.dismiss(
                    HookHistoryResult(action=HookHistoryAction.SUBMIT, command=command)
                )
                return

        # If no items match, don't submit anything
        typed_text = event.value.strip()
        if typed_text:
            self.dismiss(
                HookHistoryResult(action=HookHistoryAction.SUBMIT, command=typed_text)
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (click/double-click) - submit directly."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._filtered_items):
                self.dismiss(
                    HookHistoryResult(
                        action=HookHistoryAction.SUBMIT,
                        command=self._filtered_items[idx].command,
                    )
                )

    def action_delete_hook(self) -> None:
        """Handle Ctrl+D - delete the highlighted hook from history."""
        if not self._filtered_items:
            return

        option_list = self.query_one("#hook-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return

        if highlighted >= len(self._filtered_items):
            return

        entry = self._filtered_items[highlighted]
        delete_hook(entry.command)

        # Remove from both lists
        self._all_items = [h for h in self._all_items if h.command != entry.command]
        del self._filtered_items[highlighted]

        # Remove from OptionList
        option_list.remove_option_at_index(highlighted)

        self.notify(f"Deleted: {entry.command}")

    def action_edit_first(self) -> None:
        """Handle Ctrl+G - select and open in hooks input bar for editing."""
        command = self._get_selected_command()
        if command:
            self.dismiss(
                HookHistoryResult(action=HookHistoryAction.EDIT_FIRST, command=command)
            )
