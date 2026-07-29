"""Selectable-text fallback when clipboard transports are unavailable."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class CopyFallbackModal(ModalScreen[None]):
    """Keep generated copy text recoverable through terminal selection."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self) -> ComposeResult:
        with Container(id="copy-fallback-container"):
            yield Static(
                "No clipboard transport available — select the text below",
                id="copy-fallback-title",
            )
            yield TextArea(
                self.content,
                read_only=True,
                show_line_numbers=False,
                soft_wrap=False,
                id="copy-fallback-text",
            )
            yield Static(
                "Select with the terminal or mouse · Esc/q close",
                id="copy-fallback-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#copy-fallback-text", TextArea).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"escape", "q"}:
            return
        event.prevent_default()
        event.stop()
        self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["CopyFallbackModal"]
