"""Generic ANSI SGR styling helpers shared across CLI presentation modules."""

from __future__ import annotations

ANSI_RESET = "\x1b[0m"

_XTERM_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def _xterm256_cube_index(hex_color: str) -> int:
    hex_value = hex_color.lstrip("#")
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
    return 16 + 36 * r + 6 * g + b


def xterm256_foreground_style(hex_color: str) -> str:
    """Derive the ANSI SGR foreground escape for an xterm-256 cube color."""
    return f"\x1b[38;5;{_xterm256_cube_index(hex_color)}m"


def ansi_sgr(
    *,
    color: str | None = None,
    bold: bool = False,
    dim: bool = False,
    italic: bool = False,
    underline: bool = False,
) -> str:
    """Compose one SGR escape sequence from a hex color plus attributes."""
    codes = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if italic:
        codes.append("3")
    if underline:
        codes.append("4")
    if color is not None:
        codes.append(f"38;5;{_xterm256_cube_index(color)}")
    if not codes:
        return ""
    return f"\x1b[{';'.join(codes)}m"


def apply_ansi(value: str, style: str, *, enabled: bool) -> str:
    """Wrap ``value`` in ``style`` followed by a reset when *enabled*."""
    if not enabled or not style:
        return value
    return f"{style}{value}{ANSI_RESET}"


__all__ = [
    "ANSI_RESET",
    "ansi_sgr",
    "apply_ansi",
    "xterm256_foreground_style",
]
