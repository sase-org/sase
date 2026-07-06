"""Overlay-name prompt used by the config edit modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _OverlayNameModal(ModalScreen[str | None]):
    """Prompt for a new overlay name; dismiss with the name or ``None``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Create"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="overlay-name-container"):
            yield Label("New overlay", id="overlay-name-title")
            yield Label(
                "name → ~/.config/sase/sase_<name>.yml",
                id="overlay-name-help",
            )
            yield SingleLineVimTextArea(placeholder="work", id="overlay-name-input")
            yield Static(
                "enter / ctrl+s create · esc esc cancel", id="overlay-name-hints"
            )

    def on_mount(self) -> None:
        # A Screen's on_mount can fire before its children are mounted.
        self.call_after_refresh(self._focus_input)

    def _focus_input(self) -> None:
        try:
            editor = self.query_one("#overlay-name-input", SingleLineVimTextArea)
            editor.focus()
            editor._update_vim_mode_display()
        except Exception:
            pass

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one(
            "#overlay-name-input", SingleLineVimTextArea
        ).text.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


OverlayNameModal = _OverlayNameModal
