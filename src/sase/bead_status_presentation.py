"""Shared presentation metadata for bead statuses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast

BeadStatusValue = Literal["open", "claimed", "ready", "in_progress", "closed"]


@dataclass(frozen=True)
class _BeadStatusPresentation:
    """Cross-surface glyph, color, and label for one bead status."""

    cli_glyph: str
    tui_glyph: str
    cli_style: str
    rich_color: str
    label: str

    @property
    def glyph(self) -> str:
        """Return the glyph used by terminal CLI surfaces."""
        return self.cli_glyph

    @property
    def rich_style(self) -> str:
        """Return the standard bold Rich style used for status glyphs."""
        return f"bold {self.rich_color}"


BEAD_STATUS_PRESENTATIONS: dict[BeadStatusValue, _BeadStatusPresentation] = {
    "open": _BeadStatusPresentation(
        cli_glyph="○",
        tui_glyph="○",
        cli_style="\x1b[36m",
        rich_color="#87D7FF",
        label="OPEN",
    ),
    "claimed": _BeadStatusPresentation(
        cli_glyph="◎",
        tui_glyph="◎",
        cli_style="\x1b[35m",
        rich_color="#AF87FF",
        label="CLAIMED",
    ),
    "ready": _BeadStatusPresentation(
        cli_glyph="◇",
        tui_glyph="◇",
        cli_style="\x1b[96m",
        rich_color="#00D7AF",
        label="Ready",
    ),
    "in_progress": _BeadStatusPresentation(
        cli_glyph="◐",
        tui_glyph="◐",
        cli_style="\x1b[33m",
        rich_color="#FFD700",
        label="IN_PROGRESS",
    ),
    "closed": _BeadStatusPresentation(
        cli_glyph="✓",
        tui_glyph="●",
        cli_style="\x1b[32m",
        rich_color="#5FD787",
        label="CLOSED",
    ),
}

BEAD_STATUS_VALUES: tuple[BeadStatusValue, ...] = tuple(BEAD_STATUS_PRESENTATIONS)


def _normalize_bead_status(value: object) -> BeadStatusValue | None:
    """Return an exact normalized bead status without guessing invalid values."""
    candidate = value.value if isinstance(value, Enum) else value
    if candidate not in BEAD_STATUS_PRESENTATIONS:
        return None
    return cast(BeadStatusValue, candidate)


def bead_status_presentation(value: object) -> _BeadStatusPresentation:
    """Return presentation metadata for a valid bead status."""
    normalized = _normalize_bead_status(value)
    if normalized is None:
        raise ValueError(f"unknown bead status: {value!r}")
    return BEAD_STATUS_PRESENTATIONS[normalized]


def bead_status_display_order() -> tuple[BeadStatusValue, ...]:
    """Return bead status values in their cross-surface display order."""
    return BEAD_STATUS_VALUES


__all__ = [
    "BEAD_STATUS_PRESENTATIONS",
    "BEAD_STATUS_VALUES",
    "BeadStatusValue",
    "bead_status_display_order",
    "bead_status_presentation",
]
