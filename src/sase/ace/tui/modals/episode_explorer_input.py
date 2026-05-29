"""Input widget for the Episode Explorer modal."""

from __future__ import annotations

from .base import FilterInput


class EpisodeExplorerInput(FilterInput):
    """Filter input that keeps modal navigation available while focused."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Previous"),
        ("ctrl+r", "forward('cycle_range')", "Range"),
        ("ctrl+e", "forward('focus_inventory')", "Inventory"),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


__all__ = [
    "EpisodeExplorerInput",
]
