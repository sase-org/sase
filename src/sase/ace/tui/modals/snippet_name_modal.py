"""Snippet trigger-name modal for saving a draft as an ``ace.snippets`` entry.

Mirrors :class:`~sase.ace.tui.modals.xprompt_name_modal.XPromptNameModal` but
validates the name with the ACE snippet trigger rule
(:func:`sase.xprompt.snippet_bridge.is_valid_snippet_trigger`, i.e.
``[A-Za-z0-9_]+``) instead of the xprompt naming rule. ``existing_names`` are the
triggers already defined in the *selected* config file only, so the "already
exists" warning reflects what an overwrite would actually replace.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.xprompt.snippet_bridge import is_valid_snippet_trigger


class _NameInput(SingleLineVimTextArea):
    """Single-line vim editor for snippet trigger names."""


class SnippetNameModal(ModalScreen["str | None"]):
    """Modal for entering a snippet trigger name."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        config_path: str,
        display_path: str = "",
        existing_names: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._config_path = config_path
        self._display_path = display_path or self._shorten(config_path)
        self._existing_names = existing_names or set()

    def compose(self) -> ComposeResult:
        with Container(id="snippet-name-container"):
            yield Label("Name Snippet", id="snippet-name-title")
            yield Label(
                f"Config: {self._display_path}",
                id="snippet-name-location",
            )
            yield Label(
                "Enter snippet trigger (letters, digits, _):",
                id="snippet-name-hint",
            )
            yield _NameInput(placeholder="my_snippet", id="snippet-name-input")
            yield Label("", id="snippet-name-note")
            yield Label("", id="snippet-name-error")

    def on_mount(self) -> None:
        editor = self.query_one("#snippet-name-input", _NameInput)
        editor.focus()
        editor._update_vim_mode_display()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "snippet-name-input":
            self._update_feedback(event.text_area.text)

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        value = event.value.strip()
        error = self._validation_error(value)
        if error is not None:
            self.query_one("#snippet-name-error", Label).update(f"✗ {error}")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _update_feedback(self, raw_value: str) -> None:
        value = raw_value.strip()
        error_label = self.query_one("#snippet-name-error", Label)
        note_label = self.query_one("#snippet-name-note", Label)

        error = self._validation_error(value, allow_empty=True)
        error_label.update(f"✗ {error}" if error else "")
        if value and value in self._existing_names:
            note_label.update("Already defined here - saving will overwrite it.")
        else:
            note_label.update("")

    def _validation_error(
        self,
        value: str,
        *,
        allow_empty: bool = False,
    ) -> str | None:
        if not value:
            return None if allow_empty else "Trigger is required"
        if not is_valid_snippet_trigger(value):
            return "Use only letters, digits, and underscores"
        return None

    @staticmethod
    def _shorten(path: str) -> str:
        home = str(Path.home())
        if path.startswith(home + "/"):
            return "~" + path[len(home) :]
        return path


__all__ = ["SnippetNameModal"]
