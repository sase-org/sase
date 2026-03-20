"""Modal for creating xprompts in config files (sase.yml, default_config.yml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.xprompt.models import InputType

from .base import FilterInput

# Valid input type names for xprompt arguments.
_VALID_TYPES = {t.value for t in InputType}


@dataclass
class XPromptConfigEntry:
    """Data collected from the config entry modal."""

    name: str
    inputs: list[tuple[str, str]] = field(default_factory=list)


class XPromptConfigEntryModal(ModalScreen[XPromptConfigEntry | None]):
    """Modal for entering xprompt name and inputs for config file creation.

    Two-phase flow:
    1. Enter xprompt name, press Enter
    2. Add inputs (name type), press Enter on empty to finish
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, config_path: str) -> None:
        super().__init__()
        self._config_path = config_path
        self._name: str = ""
        self._inputs: list[tuple[str, str]] = []
        self._phase = "name"  # "name" or "inputs"

    def compose(self) -> ComposeResult:
        home_str = str(Path.home())
        display_path = self._config_path.replace(home_str, "~")
        with Container(id="config-entry-container"):
            yield Label("New Config XPrompt", id="modal-title")
            yield Label(f"File: {display_path}", id="config-entry-file-label")
            yield Label("XPrompt name:", id="config-entry-name-label")
            yield FilterInput(
                placeholder="my_prompt",
                id="config-entry-name-input",
            )
            yield Label("", id="config-entry-phase-label")
            yield FilterInput(
                placeholder="arg_name type",
                id="config-entry-input-input",
            )
            yield Static("", id="config-entry-inputs-display")
            yield Label("", id="config-entry-error")
            yield Static(
                "Enter: submit  Esc: cancel",
                id="config-entry-hints",
            )

    def on_mount(self) -> None:
        name_input = self.query_one("#config-entry-name-input", FilterInput)
        name_input.focus()
        # Hide input-phase elements initially
        self.query_one("#config-entry-phase-label", Label).update("")
        input_input = self.query_one("#config-entry-input-input", FilterInput)
        input_input.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._phase == "name":
            self._handle_name_submit(event)
        else:
            self._handle_input_submit(event)

    def _handle_name_submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.dismiss(None)
            return

        if " " in value:
            self._show_error("Name cannot contain spaces")
            return

        self._name = value
        self._phase = "inputs"

        # Disable name input, show and enable input field
        name_input = self.query_one("#config-entry-name-input", FilterInput)
        name_input.disabled = True

        phase_label = self.query_one("#config-entry-phase-label", Label)
        phase_label.update("Add input (name type), empty to finish:")

        input_input = self.query_one("#config-entry-input-input", FilterInput)
        input_input.display = True
        input_input.focus()

        types_str = ", ".join(sorted(_VALID_TYPES))
        hints = self.query_one("#config-entry-hints", Static)
        hints.update(f"Types: {types_str}  |  Enter: add/finish  Esc: cancel")

        self._clear_error()

    def _handle_input_submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            # Empty submission = done adding inputs
            self.dismiss(XPromptConfigEntry(name=self._name, inputs=list(self._inputs)))
            return

        parts = value.split()
        if len(parts) != 2:
            self._show_error("Format: name type (e.g., 'bar word')")
            return

        arg_name, arg_type = parts
        if arg_type not in _VALID_TYPES:
            types_str = ", ".join(sorted(_VALID_TYPES))
            self._show_error(f"Invalid type '{arg_type}'. Valid: {types_str}")
            return

        if any(name == arg_name for name, _ in self._inputs):
            self._show_error(f"Input '{arg_name}' already added")
            return

        self._inputs.append((arg_name, arg_type))

        # Clear the input field
        input_input = self.query_one("#config-entry-input-input", FilterInput)
        input_input.value = ""

        self._update_inputs_display()
        self._clear_error()

    def _update_inputs_display(self) -> None:
        display = self.query_one("#config-entry-inputs-display", Static)
        if not self._inputs:
            display.update("")
            return
        text = Text()
        text.append("Inputs: ", style="bold")
        for i, (name, type_str) in enumerate(self._inputs):
            if i > 0:
                text.append(", ")
            text.append(name, style="#D7AF87")
            text.append(f": {type_str}", style="dim")
        display.update(text)

    def _show_error(self, message: str) -> None:
        error_label = self.query_one("#config-entry-error", Label)
        error_label.update(message)

    def _clear_error(self) -> None:
        error_label = self.query_one("#config-entry-error", Label)
        error_label.update("")

    def action_cancel(self) -> None:
        self.dismiss(None)
