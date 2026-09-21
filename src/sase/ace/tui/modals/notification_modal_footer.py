"""Width-aware footer hint line for the notification modal."""

from __future__ import annotations

from typing import Any

from textual.events import Resize
from textual.widgets import Label

from .notification_modal_constants import (
    NOTIFICATION_HINT_FALLBACK_WIDTH,
    notification_hint_text,
)


class NotificationHintFooter(Label):
    """Footer hint line that sheds low-priority entries to fit its width.

    The hint line is a single centered row, so it cannot wrap: the widest
    footer tier that fits the measured width wins, following the same fit
    ladder as the tag strip above the list. ``q: close`` and ``+: +1`` carry
    the highest fragment priorities and survive every tier.
    """

    def __init__(
        self,
        variant: str = "default",
        **kwargs: Any,
    ) -> None:
        self._hint_variant = variant
        # Pre-layout the widget cannot measure its own width (width auto
        # sizes to the content, so a full-tier render would report its own
        # width back and never shed). Render at the 120-column modal's
        # content width instead; on_resize corrects narrower screens.
        self._hint_width = NOTIFICATION_HINT_FALLBACK_WIDTH
        super().__init__(
            notification_hint_text(variant, NOTIFICATION_HINT_FALLBACK_WIDTH),
            **kwargs,
        )

    def set_variant(self, variant: str) -> None:
        """Switch the hint variant and repaint for the current width."""
        self._hint_variant = variant
        self.update(notification_hint_text(variant, self._hint_width))

    def show_transient(self, text: str) -> None:
        """Show a one-shot line (jump mode) until the next variant update."""
        self._hint_variant = ""
        self.update(text)

    def on_resize(self, event: Resize) -> None:
        """Repaint only when a transient line is not showing."""
        width = int(event.size.width)
        if width == self._hint_width:
            return
        self._hint_width = width
        if self._hint_variant:
            self.update(notification_hint_text(self._hint_variant, width))
