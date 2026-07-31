"""Accessible Rich presentation helpers for normalized bead issue types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast

from rich.cells import cell_len
from rich.text import Text

BeadTypeValue = Literal["plan", "phase", "task"]

_ANSI_RESET = "\x1b[0m"
_XTERM_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def _xterm256_foreground_style(accent_color: str) -> str:
    """Derive the ANSI SGR foreground escape for an xterm-256 cube color.

    Deriving this from ``accent_color`` (rather than pinning a second literal)
    is what keeps the CLI's ANSI output and the Rich accent from drifting
    apart as colors are added or changed.
    """
    hex_value = accent_color.lstrip("#")
    channels = (
        int(hex_value[0:2], 16),
        int(hex_value[2:4], 16),
        int(hex_value[4:6], 16),
    )
    r, g, b = (
        min(
            range(len(_XTERM_CUBE_LEVELS)), key=lambda i: abs(_XTERM_CUBE_LEVELS[i] - c)
        )
        for c in channels
    )
    index = 16 + 36 * r + 6 * g + b
    return f"\x1b[38;5;{index}m"


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

    @property
    def cli_style(self) -> str:
        """Return the ANSI SGR foreground code matching ``accent_color``."""
        return _xterm256_foreground_style(self.accent_color)


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
    cell_len(f" {BEAD_TYPE_PRESENTATIONS[value].glyph} {value} ")
    for value in BEAD_TYPE_VALUES
)


def _normalize_bead_type(value: object) -> BeadTypeValue | None:
    """Return an exact normalized bead type without guessing invalid values."""
    candidate = value.value if isinstance(value, Enum) else value
    if candidate not in BEAD_TYPE_PRESENTATIONS:
        return None
    return cast(BeadTypeValue, candidate)


def bead_type_presentation(value: object) -> _BeadTypePresentation:
    """Return presentation metadata for a valid bead type."""
    normalized = _normalize_bead_type(value)
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
    normalized = _normalize_bead_type(value)
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


def bead_type_cli_cell(
    value: object,
    *,
    use_color: bool,
    width: int | None = None,
) -> str:
    """Return the padded glyph-only type cell for compact CLI rows.

    Unlike :func:`bead_type_chip`, this raises on an unknown type instead of
    falling back to an ``unavailable`` label: CLI rows are always built from a
    validated ``IssueType``, so a normalization failure here means a bug, not
    missing data, and should fail loudly rather than print a misleading row.
    """
    normalized = _normalize_bead_type(value)
    if normalized is None:
        raise ValueError(f"unknown bead type: {value!r}")

    presentation = BEAD_TYPE_PRESENTATIONS[normalized]
    cell = presentation.glyph
    if width is not None:
        padding = " " * max(width - cell_len(cell), 0)
    else:
        padding = ""
    if use_color:
        return f"{presentation.cli_style}{cell}{_ANSI_RESET}{padding}"
    return cell + padding


__all__ = [
    "BEAD_TYPE_CHIP_WIDTH",
    "BEAD_TYPE_PRESENTATIONS",
    "BEAD_TYPE_VALUES",
    "BeadTypeValue",
    "bead_type_chip",
    "bead_type_cli_cell",
    "bead_type_presentation",
]
