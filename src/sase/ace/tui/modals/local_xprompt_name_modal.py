"""Name modal for converting a prompt pane into a local ``xprompts:`` helper.

A small single-field modal for the ``gX`` / ``Ctrl+G X`` prompt-local keymap.
Unlike :class:`~sase.ace.tui.modals.xprompt_name_modal.XPromptNameModal` -- which
is tied to a file/config save *location* -- this one is purely about naming a
helper stored inline in the prompt bar's shared frontmatter.

The user can type a bare name (``rules``); it is normalized to the ``_``-scoped
form (``_rules``) for both the live preview and the dismissed value.  Validation
reuses the launch path's underscore-scoping rule and rejects names that collide
with the prompt's existing local helpers.  Dismisses with the normalized name on
save, or ``None`` on cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from sase.ace.tui.widgets._local_xprompt_conversion import (
    normalize_local_xprompt_name,
    validate_local_xprompt_name,
)


class _NameInput(Input):
    """Input with readline-style cursor bindings, matching the other modals."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


class LocalXPromptNameModal(ModalScreen["str | None"]):
    """Prompt for a local xprompt name; dismiss with the stored name or ``None``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, used_names: set[str] | None = None) -> None:
        super().__init__()
        self._used_names = set(used_names or ())

    def compose(self) -> ComposeResult:
        with Container(id="local-xprompt-name-container"):
            yield Label("Save Pane as Local XPrompt", id="local-xprompt-name-title")
            yield Label(
                "Enter a name (stored under xprompts:, _ prefix added):",
                id="local-xprompt-name-hint",
            )
            yield _NameInput(placeholder="rules", id="local-xprompt-name-input")
            yield Label("", id="local-xprompt-name-note")
            yield Label("", id="local-xprompt-name-error")

    def on_mount(self) -> None:
        self.query_one("#local-xprompt-name-input", _NameInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_feedback(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = normalize_local_xprompt_name(event.value)
        error = validate_local_xprompt_name(name, self._used_names)
        if error:
            self.query_one("#local-xprompt-name-error", Label).update(f"✗ {error}")
            return
        self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _update_feedback(self, raw_value: str) -> None:
        name = normalize_local_xprompt_name(raw_value)
        note_label = self.query_one("#local-xprompt-name-note", Label)
        error_label = self.query_one("#local-xprompt-name-error", Label)

        # Blank input is not an error while typing -- it is just incomplete.
        if not name:
            note_label.update("")
            error_label.update("")
            return

        note_label.update(f"stored as: {name}")
        error = validate_local_xprompt_name(name, self._used_names)
        error_label.update(f"✗ {error}" if error else "")


__all__ = ["LocalXPromptNameModal"]
