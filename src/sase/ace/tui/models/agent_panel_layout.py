"""Agents-tab panel layout ladder: Split by tribe / Merged / All tabs.

The ``o``/``O`` keys in the grouping modal walk this ladder. ``Split by
tribe`` renders one panel per tribe over the active tab, ``Merged``
renders one panel over the active tab, and ``All tabs`` renders one
panel merged over every tab. With fewer than two tabs only the first
two levels are offered (R6): a stored ``All tabs`` level renders as
``Merged`` until a second tab appears.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class AgentPanelLayout(Enum):
    """One rung of the Agents-tab panel layout ladder."""

    SPLIT = "split"
    MERGED = "merged"
    ALL_TABS = "all_tabs"


_LAYOUT_ORDER: Final[tuple[AgentPanelLayout, ...]] = (
    AgentPanelLayout.SPLIT,
    AgentPanelLayout.MERGED,
    AgentPanelLayout.ALL_TABS,
)

_SHORT_LABELS: Final[dict[AgentPanelLayout, str]] = {
    AgentPanelLayout.SPLIT: "Split by tribe",
    AgentPanelLayout.MERGED: "Merged",
    AgentPanelLayout.ALL_TABS: "All tabs",
}

_NOTIFY_LABELS: Final[dict[AgentPanelLayout, str]] = {
    AgentPanelLayout.SPLIT: "split",
    AgentPanelLayout.MERGED: "merged",
    AgentPanelLayout.ALL_TABS: "all tabs",
}

_INFO_ROW_LABELS: Final[dict[AgentPanelLayout, str]] = {
    AgentPanelLayout.SPLIT: "split",
    AgentPanelLayout.MERGED: "merged",
    AgentPanelLayout.ALL_TABS: "all tabs",
}


def layout_short_label(level: AgentPanelLayout) -> str:
    """Return the segmented-control label for *level*."""
    return _SHORT_LABELS[level]


def layout_notify_label(level: AgentPanelLayout) -> str:
    """Return the toast wording fragment for *level*."""
    return _NOTIFY_LABELS[level]


def layout_info_row_label(level: AgentPanelLayout) -> str:
    """Return the info-row ``panels:`` chip wording for *level*."""
    return _INFO_ROW_LABELS[level]


def layout_description(level: AgentPanelLayout, tab_label: str) -> str:
    """Return the modal description line for *level* naming *tab_label*."""
    tab = tab_label or "this tab"
    if level is AgentPanelLayout.SPLIT:
        return f"One panel per tribe, showing {tab} only."
    if level is AgentPanelLayout.MERGED:
        return f"One panel with every agent on {tab}."
    return "One panel with every agent on every tab."


def available_panel_layouts(has_multiple_tabs: bool) -> tuple[AgentPanelLayout, ...]:
    """Return the selectable ladder rungs (R6 two-segment mode).

    With fewer than two tabs only ``Split by tribe`` / ``Merged`` are
    offered; the stored level returns when a second tab appears.
    """
    if has_multiple_tabs:
        return _LAYOUT_ORDER
    return (AgentPanelLayout.SPLIT, AgentPanelLayout.MERGED)


def effective_panel_layout(
    stored: AgentPanelLayout, has_multiple_tabs: bool
) -> AgentPanelLayout:
    """Return the rendered level for *stored* (R6).

    A stored ``All tabs`` level renders as ``Merged`` — the same view —
    until a second tab appears.
    """
    if stored is AgentPanelLayout.ALL_TABS and not has_multiple_tabs:
        return AgentPanelLayout.MERGED
    return stored


def next_panel_layout(
    level: AgentPanelLayout,
    available: tuple[AgentPanelLayout, ...] = _LAYOUT_ORDER,
) -> AgentPanelLayout:
    """Return the level after *level*, wrapping within *available*."""
    if level not in available:
        return available[0]
    return available[(available.index(level) + 1) % len(available)]


def prev_panel_layout(
    level: AgentPanelLayout,
    available: tuple[AgentPanelLayout, ...] = _LAYOUT_ORDER,
) -> AgentPanelLayout:
    """Return the level before *level*, wrapping within *available*."""
    if level not in available:
        return available[0]
    return available[(available.index(level) - 1) % len(available)]


def panel_layout_is_merged(level: AgentPanelLayout) -> bool:
    """Return True when *level* renders one merged panel."""
    return level is not AgentPanelLayout.SPLIT


def coerce_panel_layout(value: object) -> AgentPanelLayout:
    """Return *value* as a level, falling back to ``SPLIT``."""
    if isinstance(value, AgentPanelLayout):
        return value
    if isinstance(value, str):
        for level in _LAYOUT_ORDER:
            if level.value == value:
                return level
    return AgentPanelLayout.SPLIT


__all__ = [
    "AgentPanelLayout",
    "available_panel_layouts",
    "coerce_panel_layout",
    "effective_panel_layout",
    "layout_description",
    "layout_info_row_label",
    "layout_notify_label",
    "layout_short_label",
    "next_panel_layout",
    "panel_layout_is_merged",
    "prev_panel_layout",
]
