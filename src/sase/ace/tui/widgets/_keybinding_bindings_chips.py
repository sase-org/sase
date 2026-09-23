"""Chip formatters and sort order for :class:`KeybindingFooter` bindings."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text


_CHIP_SEPARATOR = " · "
_GRID_COLUMN_GAP = 2


class KeybindingChipsMixin:
    """Shared chip formatters plus the footer sort order."""

    @staticmethod
    def _sorted_bindings(
        bindings: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        """Apply the footer sort order: symbols first, then alphabetical."""

        def _is_symbol(key: str) -> bool:
            return key.startswith("<") or (len(key) == 1 and not key[0].isalpha())

        return sorted(
            bindings,
            key=lambda x: (
                0 if _is_symbol(x[0]) else 1,
                x[0].strip("<>").lower(),
                0 if x[0][0].islower() or x[0].startswith("<") else 1,
                x[0],
            ),
        )

    @staticmethod
    def _chip_text(key: str, label: str) -> Text:
        """Single ``key⎵label`` chip — non-breaking unit."""
        chip = Text(no_wrap=True)
        chip.append(key, style="bold #00D7AF")
        chip.append(" ")
        chip.append(label, style="dim")
        return chip

    @staticmethod
    def _chip_plain_width(key: str, label: str) -> int:
        """Display width of a chip (key + space + label) in terminal cells."""
        return cell_len(key) + 1 + cell_len(label)

    def _format_bindings_inline(self, bindings: list[tuple[str, str]]) -> Text:
        """Chips joined with a dim middle-dot separator on a single line."""
        text = Text(no_wrap=True)
        sorted_b = self._sorted_bindings(bindings)
        for i, (key, label) in enumerate(sorted_b):
            if i > 0:
                text.append(_CHIP_SEPARATOR, style="dim")
            text.append_text(self._chip_text(key, label))
        return text

    def _format_bindings_grid(
        self, bindings: list[tuple[str, str]], *, columns: int
    ) -> Text:
        """Chips padded to a common cell width and flowed into ``columns``."""
        sorted_b = self._sorted_bindings(bindings)
        text = Text(no_wrap=True)
        if not sorted_b or columns < 1:
            return text
        cell_w = max(self._chip_plain_width(k, lbl) for k, lbl in sorted_b)
        n = len(sorted_b)
        for i, (key, label) in enumerate(sorted_b):
            col = i % columns
            if i > 0 and col == 0:
                text.append("\n")
            text.append_text(self._chip_text(key, label))
            is_last_in_row = col == columns - 1
            is_last_overall = i == n - 1
            if not is_last_in_row and not is_last_overall:
                pad = cell_w - self._chip_plain_width(key, label) + _GRID_COLUMN_GAP
                text.append(" " * pad)
        return text
