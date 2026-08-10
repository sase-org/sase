"""Accessible Rich presentation helpers for normalized epic phase sizes."""

from __future__ import annotations

from enum import Enum
from typing import Literal, cast

from rich.cells import cell_len
from rich.text import Text

from sase.ansi_style import ANSI_RESET, xterm256_foreground_style

PhaseSizeValue = Literal["xsmall", "small", "medium", "large", "xlarge"]

PHASE_SIZE_VALUES: tuple[PhaseSizeValue, ...] = (
    "xsmall",
    "small",
    "medium",
    "large",
    "xlarge",
)
PHASE_SIZE_STYLES: dict[PhaseSizeValue, str] = {
    "xsmall": "bold black on #5FD7AF",
    "small": "bold black on #87D7FF",
    "medium": "bold black on #FFD75F",
    "large": "bold white on #D75F87",
    "xlarge": "bold white on #AF5FFF",
}
PHASE_SIZE_CHIP_WIDTH = max(len(f" {value} ") for value in PHASE_SIZE_VALUES)

# CLI accents for each size, matching the hue embedded in PHASE_SIZE_STYLES so
# ``sase bead show``'s ``Size:`` line and the TUI chips never drift apart.
PHASE_SIZE_ACCENTS: dict[PhaseSizeValue, str] = {
    "xsmall": "#5FD7AF",
    "small": "#87D7FF",
    "medium": "#FFD75F",
    "large": "#D75F87",
    "xlarge": "#AF5FFF",
}
PHASE_SIZE_ABBREVIATIONS: dict[PhaseSizeValue, str] = {
    "xsmall": "XS",
    "small": "S",
    "medium": "M",
    "large": "L",
    "xlarge": "XL",
}
PHASE_SIZE_TOKEN_WIDTH = max(
    cell_len(token) for token in PHASE_SIZE_ABBREVIATIONS.values()
)
PHASE_SIZE_DEFAULT_MARKER = "(default)"


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


def phase_size_cli_style(value: object) -> str | None:
    """Return the ANSI SGR foreground code for a phase size, or ``None``."""
    normalized = normalize_phase_size(value)
    if normalized is None:
        return None
    return xterm256_foreground_style(PHASE_SIZE_ACCENTS[normalized])


def phase_size_cli_token(
    value: object | None,
    *,
    use_color: bool,
    width: int = PHASE_SIZE_TOKEN_WIDTH,
) -> str:
    """Return the padded compact-row token for a stored phase/task size."""
    if value is None:
        return " " * width

    normalized = normalize_phase_size(value)
    if normalized is None:
        raise ValueError(f"unknown phase size: {value!r}")

    token = PHASE_SIZE_ABBREVIATIONS[normalized]
    padding = " " * max(width - cell_len(token), 0)
    if use_color:
        return f"{padding}{xterm256_foreground_style(PHASE_SIZE_ACCENTS[normalized])}{token}{ANSI_RESET}"
    return padding + token


__all__ = [
    "PHASE_SIZE_ABBREVIATIONS",
    "PHASE_SIZE_ACCENTS",
    "PHASE_SIZE_CHIP_WIDTH",
    "PHASE_SIZE_DEFAULT_MARKER",
    "PHASE_SIZE_STYLES",
    "PHASE_SIZE_TOKEN_WIDTH",
    "PHASE_SIZE_VALUES",
    "PhaseSizeValue",
    "normalize_phase_size",
    "phase_size_chip",
    "phase_size_cli_style",
    "phase_size_cli_token",
]
