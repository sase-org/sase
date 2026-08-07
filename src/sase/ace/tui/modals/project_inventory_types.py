"""Shared value types and widgets for the inventory sub-tab panes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from textual import events

from .base import FilterInput


class InventoryIssue(Protocol):
    """Structural type for the per-project warnings an inventory scan emits."""

    @property
    def project(self) -> str: ...

    @property
    def message(self) -> str: ...


@dataclass(frozen=True)
class InventoryLoadResult[RecordT, IssueT: InventoryIssue]:
    """Rows, warnings, and load stamp returned by one background scan."""

    records: tuple[RecordT, ...]
    issues: tuple[IssueT, ...]
    loaded_at: float


class InventoryFilterInput(FilterInput):
    """Filter input that leaves pane sub-tab cycle keys available."""

    def on_key(self, event: events.Key) -> None:
        if event.key not in ("left_square_bracket", "right_square_bracket"):
            return
        node: object | None = self.parent
        while node is not None:
            if event.key == "left_square_bracket":
                action = getattr(node, "action_cycle_subtab_reverse", None)
            else:
                action = getattr(node, "action_cycle_subtab", None)
            if callable(action):
                event.stop()
                event.prevent_default()
                action()
                return
            node = getattr(node, "parent", None)


__all__ = [
    "InventoryFilterInput",
    "InventoryIssue",
    "InventoryLoadResult",
]
