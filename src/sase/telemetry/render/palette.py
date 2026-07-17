"""Fixed, deterministic colors for telemetry renderables."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

Status = Literal["ok", "warning", "critical"]

# The Admin Center accent family is the source for both palettes.  Green and
# amber are deliberately absent from CATEGORICAL_COLORS because they have
# semantic meaning in STATUS_COLORS and must never be reused for ordinary data.
ADMIN_CENTER_ACCENTS = (
    "#00D7AF",
    "#FFD700",
    "#FFAF5F",
    "#5FD75F",
    "#AF87FF",
    "#87D7FF",
)
CATEGORICAL_COLORS = (
    "#00D7AF",
    "#AF87FF",
    "#87D7FF",
    "#FF87D7",
    "#FFAF5F",
    "#5FAFFF",
)
STATUS_COLORS: dict[Status, str] = {
    "ok": "#5FD75F",
    "warning": "#FFD700",
    "critical": "#FF5F5F",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CVD_MATRICES = (
    # Protanopia, deuteranopia, and tritanopia approximations.  They are used
    # as a build-time guard against accidentally making the fixed series
    # palette indistinguishable under a common color-vision deficiency.
    ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
    ((0.625, 0.375, 0.0), (0.700, 0.300, 0.0), (0.0, 0.300, 0.700)),
    ((0.950, 0.050, 0.0), (0.0, 0.433, 0.567), (0.0, 0.475, 0.525)),
)


@dataclass(frozen=True, slots=True)
class ChartTheme:
    """Terminal-theme colors consumed by every chart component."""

    foreground: str
    muted: str
    grid: str
    axis: str
    border: str
    empty: str


DARK_THEME = ChartTheme(
    foreground="#F2F2F2",
    muted="#808080",
    grid="#444444",
    axis="#6C6C6C",
    border="#5F87AF",
    empty="#808080",
)
LIGHT_THEME = ChartTheme(
    foreground="#202020",
    muted="#666666",
    grid="#D0D0D0",
    axis="#949494",
    border="#3A628A",
    empty="#666666",
)


def categorical_color(key: str) -> str:
    """Return the stable series color assigned to an entity key.

    Assignment is based on the entity itself, not its rank or position in a
    result set.  Reordering, adding, or removing sibling series therefore
    cannot recolor an existing entity.
    """

    digest = hashlib.blake2s(key.encode("utf-8"), digest_size=2).digest()
    index = int.from_bytes(digest, byteorder="big") % len(CATEGORICAL_COLORS)
    return CATEGORICAL_COLORS[index]


def status_color(status: Status) -> str:
    """Return the reserved semantic color for *status*."""

    return STATUS_COLORS[status]


def validate_palette() -> None:
    """Raise ``ValueError`` if the fixed palette invariants are violated."""

    colors = (*CATEGORICAL_COLORS, *STATUS_COLORS.values())
    invalid = [color for color in colors if not _HEX_COLOR_RE.fullmatch(color)]
    if invalid:
        raise ValueError(f"invalid palette colors: {invalid}")
    if len(set(CATEGORICAL_COLORS)) != len(CATEGORICAL_COLORS):
        raise ValueError("categorical palette contains duplicate colors")
    overlap = set(CATEGORICAL_COLORS) & set(STATUS_COLORS.values())
    if overlap:
        raise ValueError(f"status colors reused for categorical series: {overlap}")

    # A threshold of 20 in transformed sRGB space catches near-collisions while
    # preserving the deliberately related Admin Center accent family.
    for matrix in _CVD_MATRICES:
        transformed = [
            _transform_cvd(_parse_rgb(color), matrix) for color in CATEGORICAL_COLORS
        ]
        if (
            min(_distance(left, right) for left, right in combinations(transformed, 2))
            < 20
        ):
            raise ValueError("palette colors are not distinguishable under CVD checks")


def _parse_rgb(color: str) -> tuple[float, float, float]:
    return tuple(float(int(color[index : index + 2], 16)) for index in (1, 3, 5))  # type: ignore[return-value]


def _transform_cvd(
    color: tuple[float, float, float],
    matrix: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> tuple[float, float, float]:
    return tuple(
        sum(row[column] * color[column] for column in range(3)) for row in matrix
    )  # type: ignore[return-value]


def _distance(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


validate_palette()
