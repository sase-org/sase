"""Three-way resolution for a changed bound xprompt source."""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

XPromptConflictResolution = Literal["overwrite", "reload", "save_as"]


class XPromptWriteConflictModal(ModalScreen[XPromptConflictResolution | None]):
    """Never silently clobber a definition changed since it was loaded."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str, display_path: str) -> None:
        super().__init__()
        self._name = name
        self._display_path = display_path

    def compose(self) -> ComposeResult:
        with Container(id="xprompt-conflict-container"):
            yield Label(f"#{self._name} changed on disk", id="xprompt-conflict-title")
            yield Static(self._display_path, id="xprompt-conflict-path")
            yield OptionList(
                Option(
                    Text("Overwrite disk with this draft", style="bold red"),
                    id="overwrite",
                ),
                Option("Reload the disk version", id="reload"),
                Option("Save this draft as another xprompt", id="save_as"),
                id="xprompt-conflict-options",
            )
            yield Static("enter choose · esc cancel", id="xprompt-conflict-hints")

    def on_mount(self) -> None:
        options = self.query_one("#xprompt-conflict-options", OptionList)
        options.highlighted = 1
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id in {"overwrite", "reload", "save_as"}:
            self.dismiss(event.option.id)  # type: ignore[arg-type]

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["XPromptConflictResolution", "XPromptWriteConflictModal"]
