"""Accessible Rich presentation helpers for normalized bead issue types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast

from rich.text import Text

BeadTypeValue = Literal["plan", "phase", "task"]


@dataclass(frozen=True)
class _BeadTypePresentation:
    """Cross-surface glyph, accent, and chip metadata for one bead type."""

    glyph: str
    accent_color: str
    chip_style: str
    label: str

    @property
    def rich_style(self) -> str:
        """Return the standard bold Rich style used for standalone type glyphs."""
        return f"bold {self.accent_color}"


BEAD_TYPE_PRESENTATIONS: dict[BeadTypeValue, _BeadTypePresentation] = {
    "plan": _BeadTypePresentation(
        glyph="▸",
        accent_color="#FFD700",
        chip_style="bold black on #FFD700",
        label="Plan",
    ),
    "phase": _BeadTypePresentation(
        glyph="↳",
        accent_color="#87D7FF",
        chip_style="bold black on #87D7FF",
        label="Phase",
    ),
    "task": _BeadTypePresentation(
        glyph="◆",
        accent_color="#D787FF",
        chip_style="bold black on #D787FF",
        label="Task",
    ),
}
BEAD_TYPE_VALUES: tuple[BeadTypeValue, ...] = tuple(BEAD_TYPE_PRESENTATIONS)
BEAD_TYPE_CHIP_WIDTH = max(
    len(f" {BEAD_TYPE_PRESENTATIONS[value].glyph} {value} ")
    for value in BEAD_TYPE_VALUES
)


def normalize_bead_type(value: object) -> BeadTypeValue | None:
    """Return an exact normalized bead type without guessing invalid values."""
    candidate = value.value if isinstance(value, Enum) else value
    if candidate not in BEAD_TYPE_PRESENTATIONS:
        return None
    return cast(BeadTypeValue, candidate)


def bead_type_presentation(value: object) -> _BeadTypePresentation:
    """Return presentation metadata for a valid bead type."""
    normalized = normalize_bead_type(value)
    if normalized is None:
        raise ValueError(f"unknown bead type: {value!r}")
    return BEAD_TYPE_PRESENTATIONS[normalized]


def bead_type_chip(
    value: object,
    *,
    width: int | None = None,
    unavailable_style: str = "dim italic",
) -> Text:
    """Return a literal bead-type chip or an honest unavailable value."""
    normalized = normalize_bead_type(value)
    if normalized is None:
        return Text("unavailable", style=unavailable_style)

    presentation = BEAD_TYPE_PRESENTATIONS[normalized]
    label = f" {presentation.glyph} {normalized} "
    if width is not None:
        label = label.ljust(max(width, len(label)))
    return Text(
        label,
        style=presentation.chip_style,
        overflow="crop",
        no_wrap=True,
    )


def bead_type_display_order() -> tuple[BeadTypeValue, ...]:
    """Return bead type values in their cross-surface display order."""
    return BEAD_TYPE_VALUES


__all__ = [
    "BEAD_TYPE_CHIP_WIDTH",
    "BEAD_TYPE_PRESENTATIONS",
    "BEAD_TYPE_VALUES",
    "BeadTypeValue",
    "bead_type_chip",
    "bead_type_display_order",
    "bead_type_presentation",
    "normalize_bead_type",
]
