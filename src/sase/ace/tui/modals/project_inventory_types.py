"""Shared value types and widgets for the inventory sub-tab panes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from textual import events

from sase.ace.tui.keymaps import ProjectsPaneKeymaps, split_key_alternatives

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
        keymaps = self._keymaps()
        if keymaps is None:
            return
        if event.key in split_key_alternatives(keymaps.cycle_subtab_reverse):
            action_name = "action_cycle_subtab_reverse"
        elif event.key in split_key_alternatives(keymaps.cycle_subtab):
            action_name = "action_cycle_subtab"
        else:
            return
        node: object | None = self.parent
        while node is not None:
            action = getattr(node, action_name, None)
            if callable(action):
                event.stop()
                event.prevent_default()
                action()
                return
            node = getattr(node, "parent", None)

    def _keymaps(self) -> ProjectsPaneKeymaps | None:
        node: object | None = self.parent
        while node is not None:
            keymaps = getattr(node, "_keymaps", None)
            if keymaps is not None:
                return keymaps
            node = getattr(node, "parent", None)
        return None


__all__ = [
    "InventoryFilterInput",
    "InventoryIssue",
    "InventoryLoadResult",
]
