"""Theme-derived glossary and repo-mention styles for prompt surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.style import Style

from sase.xprompt.highlight_theme import derive_argument_color


@dataclass(frozen=True, slots=True)
class SemanticHighlightStyles:
    """Bold, underlined glossary/repo roles derived from the active theme."""

    glossary: Style
    repo: Style

    @property
    def signature(self) -> str:
        """Compact cache key that changes when either derived color changes."""
        return f"{_style_color_key(self.glossary)}|{_style_color_key(self.repo)}"


def semantic_highlight_styles_from_theme(
    theme: Any | None,
) -> SemanticHighlightStyles | None:
    """Return glossary/repo styles from *theme*, or ``None`` when it is missing."""
    if theme is None:
        return None
    background = getattr(theme, "background", None) or "#000000"
    foreground = getattr(theme, "foreground", None)
    return SemanticHighlightStyles(
        glossary=Style(
            color=derive_argument_color(
                getattr(theme, "primary", None),
                foreground=foreground,
                background=background,
            ),
            bold=True,
            underline=True,
        ),
        repo=Style(
            color=derive_argument_color(
                getattr(theme, "accent", None),
                foreground=foreground,
                background=background,
            ),
            bold=True,
            underline=True,
        ),
    )


def _style_color_key(style: Style) -> str:
    color = style.color
    if color is None:
        return ""
    hex_color = getattr(color, "hex", None)
    return hex_color if isinstance(hex_color, str) else str(color)


__all__ = [
    "SemanticHighlightStyles",
    "semantic_highlight_styles_from_theme",
]
