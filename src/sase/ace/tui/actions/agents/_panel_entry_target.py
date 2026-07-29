"""Shared destination resolver for entering a whole-focused agent panel."""

from __future__ import annotations

from typing import Any, Literal

type PanelSelectionStop = tuple[
    Literal["agent", "banner"],
    int | tuple[str, ...],
]


def resolve_panel_entry_stop(
    owner: Any,
    panel_key: str | None,
) -> PanelSelectionStop | None:
    """Return the stop that entering ``panel_key`` selects, or ``None``."""
    stops_fn = getattr(owner, "_panel_navigation_stops", None)
    stops: list[PanelSelectionStop] = []
    if callable(stops_fn):
        try:
            stops = stops_fn(include_panel_focus=True)
        except TypeError:
            stops = stops_fn()
    remembered = getattr(owner, "_panel_selection_memory", {}).get(panel_key)
    return remembered if remembered in stops else (stops[0] if stops else None)


__all__ = ["PanelSelectionStop", "resolve_panel_entry_stop"]
