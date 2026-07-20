"""Accessible Rich presentation helpers for normalized epic phase sizes."""

from __future__ import annotations

from enum import Enum
from typing import Literal, cast

from rich.text import Text

PhaseSizeValue = Literal["small", "medium", "large"]

PHASE_SIZE_VALUES: tuple[PhaseSizeValue, ...] = ("small", "medium", "large")
PHASE_SIZE_STYLES: dict[PhaseSizeValue, str] = {
    "small": "bold black on #87D7FF",
    "medium": "bold black on #FFD75F",
    "large": "bold white on #D75F87",
}
PHASE_SIZE_CHIP_WIDTH = max(len(f" {value} ") for value in PHASE_SIZE_VALUES)


def normalize_phase_size(value: object) -> PhaseSizeValue | None:
    """Return an exact normalized phase size without guessing invalid values."""
    candidate = value.value if isinstance(value, Enum) else value
    if candidate not in PHASE_SIZE_VALUES:
        return None
    return cast(PhaseSizeValue, candidate)


def phase_size_chip(
    value: object,
    *,
    width: int | None = None,
    unavailable_style: str = "dim italic",
) -> Text:
    """Return a literal phase-size chip or an honest unavailable value."""
    normalized = normalize_phase_size(value)
    if normalized is None:
        return Text("unavailable", style=unavailable_style)

    label = f" {normalized} "
    if width is not None:
        label = label.ljust(max(width, len(label)))
    return Text(
        label,
        style=PHASE_SIZE_STYLES[normalized],
        overflow="crop",
        no_wrap=True,
    )


__all__ = [
    "PHASE_SIZE_CHIP_WIDTH",
    "PHASE_SIZE_STYLES",
    "PHASE_SIZE_VALUES",
    "PhaseSizeValue",
    "normalize_phase_size",
    "phase_size_chip",
]
