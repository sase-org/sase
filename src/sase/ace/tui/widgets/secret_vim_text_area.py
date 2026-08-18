"""Masked single-line :class:`SingleLineVimTextArea` for secret fields.

Masking is shoulder-surfing protection only: ``.text`` / ``.value`` still
return the real characters, and the vim registers and the app clipboard hold
the unmasked value -- matching what ``Input(password=True)`` gave before.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.segment import Segment
from textual.strip import Strip

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

__all__ = ["SecretVimTextArea"]


class SecretVimTextArea(SingleLineVimTextArea):
    """Single-line vim editor that paints bullets instead of its real text.

    Only rendering is masked. Empty text is left unmasked so the placeholder
    still reads as placeholder text rather than a row of bullets.
    """

    def render_line(self, y: int) -> Strip:
        """Mask the painted line; keep segment styles and the strip cell length."""
        strip = super().render_line(y)
        if self.text == "":
            return strip
        return Strip(
            [
                Segment(
                    "•" * cell_len(segment.text),
                    segment.style,
                    segment.control,
                )
                for segment in strip
            ],
            strip.cell_length,
        )
