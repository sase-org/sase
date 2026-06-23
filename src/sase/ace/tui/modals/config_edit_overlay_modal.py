"""Overlay-name prompt used by the config edit modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


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
            yield Input(placeholder="work", id="overlay-name-input")
            yield Static("enter / ctrl+s create · esc cancel", id="overlay-name-hints")

    def on_mount(self) -> None:
        # A Screen's on_mount can fire before its children are mounted.
        self.call_after_refresh(self._focus_input)

    def _focus_input(self) -> None:
        try:
            self.query_one("#overlay-name-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one("#overlay-name-input", Input).value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


OverlayNameModal = _OverlayNameModal
