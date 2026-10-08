"""Modal for creating macros in config files (sase.yml, default_config.yml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.macro.frontmatter_schema import input_type_schema
from sase.macro.loader_parsing import parse_input_type
from sase.macro.models import InputType, MacroValidationError


def _advertised_config_type_names() -> list[str]:
    """Return sorted advertised catalog type names for the hint line."""
    return sorted(descriptor.name for descriptor in input_type_schema())


def _validate_config_input_type(arg_name: str, arg_type: str) -> str | None:
    """Return an error message for a config ``name type`` pair, or None when valid.

    Uses the Rust-backed resolver so builtin, named, and plugin types resolve
    the same way as the frontmatter panel. Inline ``enum`` is rejected because
    a shortform pair cannot declare ``choices``.
    """
    try:
        resolved = parse_input_type(arg_type, name=arg_name)
    except MacroValidationError as exc:
        return str(exc)
    if resolved.base is InputType.ENUM and resolved.named_type is None:
        return (
            "Type 'enum' needs `choices` declared in the config file; "
            "use a named type like 'effort' for shared choices"
        )
    return None


@dataclass
class MacroConfigEntry:
    """Data collected from the config entry modal."""

    name: str
    inputs: list[tuple[str, str]] = field(default_factory=list)


class _ConfigEntryInput(SingleLineVimTextArea):
    """Single-line vim editor for config macro entry fields."""


class MacroConfigEntryModal(ModalScreen[MacroConfigEntry | None]):
    """Modal for entering macro name and inputs for config file creation.

    Two-phase flow:
    1. Enter macro name, press Enter
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
            yield Label("New Config Macro", id="modal-title")
            yield Label(f"File: {display_path}", id="config-entry-file-label")
            yield Label("Macro name:", id="config-entry-name-label")
            yield _ConfigEntryInput(
                placeholder="my_prompt",
                id="config-entry-name-input",
            )
            yield Label("", id="config-entry-phase-label")
            yield _ConfigEntryInput(
                placeholder="arg_name type",
                id="config-entry-input-input",
            )
            yield Static("", id="config-entry-inputs-display")
            yield Label("", id="config-entry-error")
            yield Static(
                "Enter: submit  Esc Esc: cancel",
                id="config-entry-hints",
            )

    def on_mount(self) -> None:
        name_input = self.query_one("#config-entry-name-input", _ConfigEntryInput)
        name_input.focus()
        name_input._update_vim_mode_display()
        # Hide input-phase elements initially
        self.query_one("#config-entry-phase-label", Label).update("")
        input_input = self.query_one("#config-entry-input-input", _ConfigEntryInput)
        input_input.display = False

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        if self._phase == "name":
            self._handle_name_submit(event)
        else:
            self._handle_input_submit(event)

    def _handle_name_submit(self, event: SingleLineVimTextArea.Submitted) -> None:
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
        name_input = self.query_one("#config-entry-name-input", _ConfigEntryInput)
        name_input.disabled = True

        phase_label = self.query_one("#config-entry-phase-label", Label)
        phase_label.update("Add input (name type), empty to finish:")

        input_input = self.query_one("#config-entry-input-input", _ConfigEntryInput)
        input_input.display = True
        input_input.focus()
        input_input._update_vim_mode_display()

        types_str = ", ".join(_advertised_config_type_names())
        hints = self.query_one("#config-entry-hints", Static)
        hints.update(f"Types: {types_str}  |  Enter: add/finish  Esc Esc: cancel")

        self._clear_error()

    def _handle_input_submit(self, event: SingleLineVimTextArea.Submitted) -> None:
        value = event.value.strip()
        if not value:
            # Empty submission = done adding inputs
            self.dismiss(MacroConfigEntry(name=self._name, inputs=list(self._inputs)))
            return

        parts = value.split()
        if len(parts) != 2:
            self._show_error("Format: name type (e.g., 'bar word')")
            return

        arg_name, arg_type = parts
        if (error := _validate_config_input_type(arg_name, arg_type)) is not None:
            self._show_error(error)
            return

        if any(name == arg_name for name, _ in self._inputs):
            self._show_error(f"Input '{arg_name}' already added")
            return

        self._inputs.append((arg_name, arg_type))

        # Clear the input field
        input_input = self.query_one("#config-entry-input-input", _ConfigEntryInput)
        input_input.text = ""

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
