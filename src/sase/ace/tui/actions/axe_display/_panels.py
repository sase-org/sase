"""Panel partition index over the Services-tab sidebar item list.

The sidebar keeps one global flat ``_axe_items`` list (so row actions,
identity restore, and the jump-all modal keep their meaning), while the two
statically composed :class:`BgCmdList` panels each render a local slice of
it. This module maps between global and panel-local indices without
importing Textual, so unit tests exercise it without a running app.

Panel membership is derived from the item's class name rather than an
isinstance check so this module never imports the widget layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

ServicesPanelKey = Literal["service_procs", "scheduled_routines"]

SERVICES_PANEL_ORDER: tuple[ServicesPanelKey, ServicesPanelKey] = (
    "service_procs",
    "scheduled_routines",
)

_SERVICE_PROCS_ITEM_CLASSES = frozenset({"ServiceProcItem", "BgCmdItem"})
_SCHEDULED_ROUTINES_ITEM_CLASSES = frozenset({"LumberjackItem", "ChopItem"})


def _services_panel_key_for_item(item: object) -> ServicesPanelKey:
    """Return the panel that renders ``item``.

    ``ServiceProcItem`` and ``BgCmdItem`` (oneshots) belong to the Service
    Procs panel; ``LumberjackItem`` and ``ChopItem`` belong to Scheduled
    Routines. Raises :class:`TypeError` for anything else so a new item
    type fails loudly instead of silently landing in the wrong panel.
    """
    class_name = type(item).__name__
    if class_name in _SERVICE_PROCS_ITEM_CLASSES:
        return "service_procs"
    if class_name in _SCHEDULED_ROUTINES_ITEM_CLASSES:
        return "scheduled_routines"
    raise TypeError(f"Unknown Services-tab sidebar item type: {class_name!r}")


@dataclass
class _ServicesPanelSlice:
    """The items of one panel, with reverse-index maps."""

    items: list[object] = field(default_factory=list)
    global_indices: list[int] = field(default_factory=list)
    global_to_local: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ServicesPanelIndex:
    """O(1) lookup of panel slices over a Services item list."""

    panels: dict[ServicesPanelKey, _ServicesPanelSlice] = field(default_factory=dict)

    def slice_for(self, key: ServicesPanelKey) -> _ServicesPanelSlice:
        """Return the slice for ``key`` (empty when the panel has no rows)."""
        return self.panels.get(key, _ServicesPanelSlice())

    def panel_for_global(self, global_idx: int) -> ServicesPanelKey:
        """Return the panel holding ``global_idx``.

        Falls back to ``"service_procs"`` for an empty or out-of-range
        index so the focused panel always has a defined value.
        """
        for key in SERVICES_PANEL_ORDER:
            if (
                global_idx
                in self.panels.get(key, _ServicesPanelSlice()).global_to_local
            ):
                return key
        return "service_procs"

    def local_idx_for(self, key: ServicesPanelKey, global_idx: int) -> int:
        """Return the panel-local index of ``global_idx`` in panel ``key``.

        Returns ``-1`` when the global index does not belong to that panel
        (the sentinel ``BgCmdList`` treats as "no highlight").
        """
        return self.panels.get(key, _ServicesPanelSlice()).global_to_local.get(
            global_idx, -1
        )

    def first_global(self, key: ServicesPanelKey) -> int | None:
        """Return the first global index rendered in panel ``key``."""
        indices = self.panels.get(key, _ServicesPanelSlice()).global_indices
        return indices[0] if indices else None

    def last_global(self, key: ServicesPanelKey) -> int | None:
        """Return the last global index rendered in panel ``key``."""
        indices = self.panels.get(key, _ServicesPanelSlice()).global_indices
        return indices[-1] if indices else None

    def adjacent_nonempty_panel(
        self, current_key: ServicesPanelKey, *, forward: bool
    ) -> ServicesPanelKey | None:
        """Return the next/previous panel holding at least one nav item.

        Walks ``SERVICES_PANEL_ORDER`` with wrap, skipping empty panels,
        and never returns ``current_key``. Returns ``None`` when no other
        panel has nav items.
        """
        order = SERVICES_PANEL_ORDER
        start = order.index(current_key)
        step = 1 if forward else -1
        for offset in range(1, len(order) + 1):
            candidate = order[(start + step * offset) % len(order)]
            if candidate == current_key:
                continue
            if self.panels.get(candidate, _ServicesPanelSlice()).global_indices:
                return candidate
        return None


def build_services_panel_index(items: Sequence[object]) -> ServicesPanelIndex:
    """Build a :class:`ServicesPanelIndex` over ``items`` in visual order."""
    panels: dict[ServicesPanelKey, _ServicesPanelSlice] = {}
    for global_idx, item in enumerate(items):
        key = _services_panel_key_for_item(item)
        slot = panels.get(key)
        if slot is None:
            slot = _ServicesPanelSlice()
            panels[key] = slot
        slot.global_to_local[global_idx] = len(slot.items)
        slot.items.append(item)
        slot.global_indices.append(global_idx)
    return ServicesPanelIndex(panels=panels)
