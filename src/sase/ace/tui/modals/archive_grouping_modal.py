"""Compact picker for Agents Archive grouping modes."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ArchiveGroupingModal(ModalScreen[str | None]):
    """Choose the Archive's day, project, outcome, or model grouping."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("q", "cancel", "Cancel")]
    CHOICES = (("d", "day"), ("p", "project"), ("o", "outcome"), ("m", "model"))

    def __init__(self, current: str = "day") -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="archive-grouping-container"):
            yield Static("Archive grouping", id="archive-grouping-title")
            with Vertical(id="archive-grouping-options"):
                for key, name in self.CHOICES:
                    marker = "●" if name == self._current else "○"
                    yield Static(f"{marker}  {key}  {name}")
            yield Static(
                "d day · p project · o outcome · m model · enter select · esc cancel"
            )

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.dismiss(self._current)
            return
        for key, name in self.CHOICES:
            if event.key == key:
                event.stop()
                event.prevent_default()
                self.dismiss(name)
                return

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["ArchiveGroupingModal"]
