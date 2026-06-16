"""Add-property picker for the prompt Frontmatter Panel (Phase 3).

A small option-list modal that lists the frontmatter fields the user has **not**
set yet, each with the one-line description sourced from ``sase-core`` (the same
schema that backs the xprompt LSP), and returns the chosen field name.  The panel
then drops into that field's inline editor.

Only inline-editable fields (scalars / lists / bool-or-X) are offered here; the
structured ``input`` / ``xprompts`` fields are authored via the panel's raw-YAML
mode in Phase 3 and gain dedicated editors in Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from .base import OptionListNavigationMixin


@dataclass(frozen=True)
class AddableProperty:
    """One pickable frontmatter field: its key and core description."""

    name: str
    description: str


class AddPropertyModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Pick a frontmatter property to add; dismiss with its name (or ``None``)."""

    _option_list_id = "add-property-list"
    BINDINGS = [*OptionListNavigationMixin.NAVIGATION_BINDINGS]

    def __init__(self, properties: list[AddableProperty]) -> None:
        super().__init__()
        self._properties = properties

    def compose(self) -> ComposeResult:
        """Compose the picker: a title above a scrollable option list."""
        with Container(id="add-property-modal-container"):
            yield Label("Add frontmatter property", id="modal-title")
            yield OptionList(
                *[
                    Option(self._styled_label(prop), id=prop.name)
                    for prop in self._properties
                ],
                id="add-property-list",
            )

    @staticmethod
    def _styled_label(prop: AddableProperty) -> Text:
        """Render one row: the field key in accent, its core description dimmed."""
        text = Text()
        text.append(prop.name, style="bold #87D7FF")
        if prop.description:
            text.append(f"  {prop.description}", style="dim")
        return text

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the selected field name to the caller."""
        if event.option and event.option.id:
            self.dismiss(str(event.option.id))
