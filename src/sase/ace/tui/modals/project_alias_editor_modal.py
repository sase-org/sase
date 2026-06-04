"""Project alias editor modal for the ace TUI."""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class _ProjectAliasInput(Input):
    """Input widget with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


class ProjectAliasEditorModal(ModalScreen[list[str] | None]):
    """Edit the comma-separated aliases for one project."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, project_name: str, aliases: Sequence[str]) -> None:
        super().__init__()
        self._project_name = project_name
        self._aliases = list(aliases)

    def compose(self) -> ComposeResult:
        with Container(id="project-alias-editor-container"):
            yield Label(f"Aliases: {self._project_name}", id="modal-title")
            yield _ProjectAliasInput(
                value=", ".join(self._aliases),
                placeholder="alias-one, alias-two",
                id="project-alias-input",
            )
            yield Label("Comma-separated project aliases.", id="project-alias-hint")
            with Horizontal(id="project-alias-buttons"):
                yield Button("Save Aliases", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        alias_input = self.query_one("#project-alias-input", _ProjectAliasInput)
        alias_input.focus()
        alias_input.cursor_position = len(alias_input.value)

    def _aliases_from_value(self, value: str) -> list[str]:
        return [alias.strip() for alias in value.split(",") if alias.strip()]

    def _submit_value(self, value: str) -> None:
        self.dismiss(self._aliases_from_value(value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            alias_input = self.query_one("#project-alias-input", Input)
            self._submit_value(alias_input.value)
            return
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_value(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["ProjectAliasEditorModal"]
