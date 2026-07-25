"""Kind-specific fold scales for Agents-tab summary documents."""

from __future__ import annotations

from .fold_state import FoldLevel

type FoldScale = tuple[FoldLevel, ...]

FAMILY_FOLD_SCALE: FoldScale = (
    FoldLevel.EXPANDED,
    FoldLevel.FULLY_EXPANDED,
)
CLAN_FOLD_SCALE: FoldScale = (
    FoldLevel.COLLAPSED,
    FoldLevel.EXPANDED,
    FoldLevel.FULLY_EXPANDED,
)
AGENT_FOLD_SCALE: FoldScale = CLAN_FOLD_SCALE
TRIBE_FOLD_SCALE: FoldScale = (
    FoldLevel.COLLAPSED,
    FoldLevel.EXPANDED,
    FoldLevel.FULLY_EXPANDED,
    FoldLevel.EXHAUSTIVE,
)

_FOLD_LEVEL_ORDER = TRIBE_FOLD_SCALE


def fold_level_at_position(position: int, scale: FoldScale) -> FoldLevel | None:
    """Resolve a one-based ``position`` within ``scale`` exactly.

    Direct fold commands name the displayed position in a kind-specific
    scale, not the ordinal of :class:`FoldLevel`.  Invalid positions are
    rejected rather than clamped so callers can consume an unsupported chord
    without changing fold state.
    """
    if position < 1 or position > len(scale):
        return None
    return scale[position - 1]


def resolve_summary_fold_scale(
    *,
    whole_panel_focused: bool,
    group_focused: bool = False,
    agent: object | None,
) -> FoldScale | None:
    """Return the lane or aggregate scale selected by the current UI context."""
    if whole_panel_focused:
        return TRIBE_FOLD_SCALE
    if group_focused or agent is None:
        return None
    if getattr(agent, "is_clan_container", False):
        return CLAN_FOLD_SCALE
    return lane_fold_scale(agent)


def lane_fold_scale(agent: object) -> FoldScale:
    """Return the fold scale owned by one agent lane's summary document."""
    return (
        FAMILY_FOLD_SCALE
        if getattr(agent, "is_family_container_row", False)
        else AGENT_FOLD_SCALE
    )


def effective_fold_level(level: FoldLevel, scale: FoldScale) -> FoldLevel:
    """Clamp ``level`` to the nearest usable level in ``scale``.

    Fold scales are ordered subsets of the global fold ladder.  A shared level
    below a kind's first usable level maps up to that first level; a shared
    level above its last usable level maps down to the last level.
    """
    if not scale:
        raise ValueError("fold scale must contain at least one level")
    if level in scale:
        return level

    level_index = _FOLD_LEVEL_ORDER.index(level)
    scale_indices = tuple(_FOLD_LEVEL_ORDER.index(candidate) for candidate in scale)
    if level_index <= scale_indices[0]:
        return scale[0]
    if level_index >= scale_indices[-1]:
        return scale[-1]
    for candidate, candidate_index in zip(
        reversed(scale),
        reversed(scale_indices),
        strict=True,
    ):
        if candidate_index <= level_index:
            return candidate
    return scale[0]


def fold_scale_position(level: FoldLevel, scale: FoldScale) -> tuple[int, int]:
    """Return the one-based effective position and size of ``scale``."""
    effective = effective_fold_level(level, scale)
    return scale.index(effective) + 1, len(scale)


def cycle_fold_level_forward(level: FoldLevel, scale: FoldScale) -> FoldLevel:
    """Cycle forward from ``level`` within ``scale``, wrapping at the end."""
    effective = effective_fold_level(level, scale)
    return scale[(scale.index(effective) + 1) % len(scale)]


def toggle_fold_scale_extreme(level: FoldLevel, scale: FoldScale) -> FoldLevel:
    """Open to ``scale``'s maximum, or close its effective maximum."""
    effective = effective_fold_level(level, scale)
    return scale[0] if effective == scale[-1] else scale[-1]


def toggle_fold_level(level: FoldLevel, scale: FoldScale) -> FoldLevel:
    """Toggle between the first and last effective levels in ``scale``."""
    effective = effective_fold_level(level, scale)
    return scale[-1] if effective == scale[0] else scale[0]


__all__ = [
    "AGENT_FOLD_SCALE",
    "CLAN_FOLD_SCALE",
    "FAMILY_FOLD_SCALE",
    "TRIBE_FOLD_SCALE",
    "FoldScale",
    "cycle_fold_level_forward",
    "effective_fold_level",
    "fold_level_at_position",
    "fold_scale_position",
    "lane_fold_scale",
    "resolve_summary_fold_scale",
    "toggle_fold_scale_extreme",
    "toggle_fold_level",
]
