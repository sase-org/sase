"""Shared presentation language for fold-aware agent documents."""

from __future__ import annotations

from rich.text import Text

from ...models.fold_scale import FoldScale, fold_scale_position
from ...models.fold_state import FoldLevel

FOLD_CHARS: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "▸",
    FoldLevel.EXPANDED: "▾",
    FoldLevel.FULLY_EXPANDED: "▼",
    FoldLevel.EXHAUSTIVE: "◆",
}
FOLD_STYLES: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "#5F5F5F",
    FoldLevel.EXPANDED: "#00D7AF",
    FoldLevel.FULLY_EXPANDED: "bold #87FFD7",
    FoldLevel.EXHAUSTIVE: "bold #FFFFFF",
}

_ATTENTION_TITLES = frozenset({"NEEDS ATTENTION", "ERRORS"})
_FIELD_LABEL_STYLE = "bold #87D7FF"
_FOLD_VALUE_STYLE = "dim #D75FFF"
_FAILURE_COUNT_STYLE = "bold #FF5F5F"


def append_fold_glyph(text: Text, level: FoldLevel) -> None:
    """Append the shared glyph and style for one effective fold level."""
    text.append(f"{FOLD_CHARS[level]} ", style=FOLD_STYLES[level])


def append_fold_header_line(
    text: Text,
    *,
    level: FoldLevel,
    scale: FoldScale,
) -> None:
    """Append a kind-aware ``Fold: N/M`` header line."""
    position, size = fold_scale_position(level, scale)
    text.append("Fold: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{position}/{size}\n", style=_FOLD_VALUE_STYLE)


def append_scanning_tail(text: Text) -> None:
    """Append the single document-level marker for pending enrichment."""
    text.append("\n⋯ scanning member data…\n", style="dim italic")


def fold_count_style(title: str) -> str:
    """Return the shared count style, accenting problem-signal headings."""
    return _FAILURE_COUNT_STYLE if title in _ATTENTION_TITLES else "dim"


__all__ = [
    "FOLD_CHARS",
    "FOLD_STYLES",
    "append_fold_glyph",
    "append_fold_header_line",
    "append_scanning_tail",
    "fold_count_style",
]
