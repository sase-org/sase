"""Selectable one-line Inbox pulse shown above the Archive list."""

from __future__ import annotations

from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from ...models.agent_archive_controller import ArchiveInboxPulse
from ._rows import format_pulse


class ArchivePulse(Static):
    """``⌂ Inbox · N [R… W… U…] · M needs you``; Enter, ``l``, or click returns."""

    class Activated(Message):
        """The pulse was clicked: return to the parked Inbox."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__("", **kwargs)  # type: ignore[arg-type]
        self._pulse = ArchiveInboxPulse()
        self._selected = False
        self._repaint()

    def _repaint(self) -> None:
        self.update(format_pulse(self._pulse, selected=self._selected))

    def set_pulse(self, pulse: ArchiveInboxPulse) -> None:
        """Update counts. A no-op repaint is skipped so live ticks stay cheap."""
        if pulse == self._pulse:
            return
        self._pulse = pulse
        self._repaint()

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.set_class(selected, "-selected")
        self._repaint()

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Activated())


__all__ = ["ArchivePulse"]
