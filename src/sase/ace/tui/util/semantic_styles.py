"""Theme-derived glossary, repo-mention, and bead-mention styles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.style import Style

from sase.bead_status_presentation import (
    BEAD_STATUS_VALUES,
    bead_status_presentation,
)
from sase.macro.highlight_theme import derive_argument_color

#: Overlay style-name prefix for resolved bead mentions, suffixed by status.
BEAD_MENTION_STYLE_PREFIX = "bead.mention."


def bead_mention_style_name(status: str) -> str:
    """Return the overlay style name for a resolved bead *status*."""
    return f"{BEAD_MENTION_STYLE_PREFIX}{status}"


@dataclass(frozen=True, slots=True)
class SemanticHighlightStyles:
    """Bold, underlined glossary/repo/bead roles derived from the active theme."""

    glossary: Style
    repo: Style
    bead: dict[str, Style] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        """Compact cache key that changes when any derived color changes."""
        bead_key = ",".join(
            f"{status}={_style_color_key(self.bead[status])}"
            for status in sorted(self.bead)
        )
        return (
            f"{_style_color_key(self.glossary)}"
            f"|{_style_color_key(self.repo)}"
            f"|{bead_key}"
        )


def semantic_highlight_styles_from_theme(
    theme: Any | None,
) -> SemanticHighlightStyles | None:
    """Return glossary/repo/bead styles from *theme*, or ``None`` when missing."""
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
        bead={
            status: Style(
                color=derive_argument_color(
                    bead_status_presentation(status).rich_color,
                    foreground=foreground,
                    background=background,
                ),
                bold=True,
                underline=True,
            )
            for status in BEAD_STATUS_VALUES
        },
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
