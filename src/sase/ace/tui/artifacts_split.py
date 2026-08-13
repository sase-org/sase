"""Widget-free sizing and rendering helpers for Artifacts split modes."""

from __future__ import annotations

from math import floor
from typing import Literal

from rich.text import Text


ArtifactsSplitMode = Literal["narrow", "even", "wide"]

ARTIFACTS_SPLIT_MODE_ORDER: tuple[ArtifactsSplitMode, ...] = (
    "narrow",
    "even",
    "wide",
)
DEFAULT_ARTIFACTS_SPLIT_MODE: ArtifactsSplitMode = "even"
ARTIFACTS_SPLIT_CLASSES: dict[ArtifactsSplitMode, str] = {
    "narrow": "-split-narrow",
    "even": "-split-even",
    "wide": "-split-wide",
}
ARTIFACTS_SPLIT_LEFT_FRACTION: dict[ArtifactsSplitMode, float] = {
    "narrow": 0.30,
    "even": 0.50,
    "wide": 0.70,
}
ARTIFACTS_SPLIT_BADGE_FILLED: dict[ArtifactsSplitMode, int] = {
    "narrow": 1,
    "even": 2,
    "wide": 3,
}
ARTIFACTS_SPLIT_BADGE_CELLS = 4


def normalize_artifacts_split_mode(value: object) -> ArtifactsSplitMode:
    """Return a supported split mode, falling back to the session default."""

    if value in ARTIFACTS_SPLIT_MODE_ORDER:
        return value  # type: ignore[return-value]
    return DEFAULT_ARTIFACTS_SPLIT_MODE


def cycle_artifacts_split_mode(
    mode: object,
    direction: int,
) -> ArtifactsSplitMode:
    """Cycle *mode* with wraparound in the sign of *direction*."""

    normalized = normalize_artifacts_split_mode(mode)
    index = ARTIFACTS_SPLIT_MODE_ORDER.index(normalized)
    step = 1 if direction >= 0 else -1
    return ARTIFACTS_SPLIT_MODE_ORDER[(index + step) % len(ARTIFACTS_SPLIT_MODE_ORDER)]


def artifacts_split_left_cap(
    mode: object,
    available_width: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Cap a content-sized left panel for the selected split mode."""

    if available_width <= 0:
        return maximum
    fraction = ARTIFACTS_SPLIT_LEFT_FRACTION[normalize_artifacts_split_mode(mode)]
    return max(minimum, min(maximum, floor(available_width * fraction)))


def build_artifacts_split_badge(mode: object, accent: str) -> Text:
    """Render the brace-framed four-cell split indicator."""

    normalized = normalize_artifacts_split_mode(mode)
    filled = ARTIFACTS_SPLIT_BADGE_FILLED[normalized]
    text = Text("{", style="#666666")
    text.append("█" * filled, style=accent)
    text.append(
        "█" * (ARTIFACTS_SPLIT_BADGE_CELLS - filled),
        style="#3A3A3A",
    )
    text.append("}", style="#666666")
    return text


__all__ = [
    "ARTIFACTS_SPLIT_BADGE_CELLS",
    "ARTIFACTS_SPLIT_BADGE_FILLED",
    "ARTIFACTS_SPLIT_CLASSES",
    "ARTIFACTS_SPLIT_LEFT_FRACTION",
    "ARTIFACTS_SPLIT_MODE_ORDER",
    "DEFAULT_ARTIFACTS_SPLIT_MODE",
    "ArtifactsSplitMode",
    "artifacts_split_left_cap",
    "build_artifacts_split_badge",
    "cycle_artifacts_split_mode",
    "normalize_artifacts_split_mode",
]
