"""Panel partition index over the Services-tab sidebar item list.

The sidebar keeps one global flat ``_axe_items`` list (so row actions,
identity restore, and the jump-all modal keep their meaning), while the
statically composed :class:`BgCmdList` panels each render a local slice of
it. This module maps between global and panel-local indices without
importing Textual, so unit tests exercise it without a running app.

Panel membership is derived from the item's class name rather than an
isinstance check so this module never imports the widget layer. Routine
rows (``LumberjackItem`` and ``ChopItem``) resolve through the cached
parent routine origin: jobs always render in their parent routine's
panel, so a job's own origin never splits it from its parent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ServicesPanelKey = Literal[
    "service_procs", "user_routines", "plugin_routines", "builtin_routines"
]

SERVICES_PANEL_ORDER: tuple[
    ServicesPanelKey, ServicesPanelKey, ServicesPanelKey, ServicesPanelKey
] = (
    "service_procs",
    "user_routines",
    "plugin_routines",
    "builtin_routines",
)

ROUTINE_PANEL_ORDER: tuple[ServicesPanelKey, ServicesPanelKey, ServicesPanelKey] = (
    "user_routines",
    "plugin_routines",
    "builtin_routines",
)

_SOURCE_TO_PANEL: dict[str, ServicesPanelKey] = {
    "user": "user_routines",
    "plugin": "plugin_routines",
    "builtin": "builtin_routines",
}

_SERVICE_PROCS_ITEM_CLASSES = frozenset({"ServiceProcItem", "BgCmdItem"})
_ROUTINE_ITEM_CLASSES = frozenset({"LumberjackItem", "ChopItem"})


def routine_panel_key_for_source(source: str) -> ServicesPanelKey:
    """Return the routine panel for a declaring ``source``.

    Raises :class:`ValueError` for anything outside the closed
    ``builtin | plugin | user`` set so a new source value fails loudly
    instead of silently landing in the wrong panel.
    """
    try:
        return _SOURCE_TO_PANEL[source]
    except KeyError:
        expected = "builtin|plugin|user"
        raise ValueError(
            f"Unknown routine declaring source {source!r}: expected one of ({expected})"
        ) from None


def _routine_name_for_item(item: object) -> str:
    """Return the parent routine name governing ``item``'s panel."""
    class_name = type(item).__name__
    if class_name == "LumberjackItem":
        name = getattr(item, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"Routine item has no name: {item!r}")
        return name
    if class_name == "ChopItem":
        parent = getattr(item, "lumberjack_name", None)
        if not isinstance(parent, str) or not parent:
            raise ValueError(f"Job item has no parent routine: {item!r}")
        return parent
    raise TypeError(f"Not a routine item: {class_name!r}")


def _source_for_routine(
    routine_name: str, routine_origins: Mapping[str, Any] | None
) -> str:
    """Return the declaring source string for ``routine_name``."""
    if routine_origins is None or routine_name not in routine_origins:
        # Degraded configs and unit seeds may list a routine without a
        # cached origin; keep the row visible in User rather than
        # dropping it. Real collector payloads apply names and origins
        # atomically, so this only triggers off the happy path.
        return "user"
    origin: Any = routine_origins[routine_name]
    source: Any = getattr(origin, "source", origin)
    if isinstance(source, str) and source in _SOURCE_TO_PANEL:
        return source
    if isinstance(origin, Mapping):
        candidate = origin.get("source")
        if isinstance(candidate, str) and candidate in _SOURCE_TO_PANEL:
            return candidate
    raise ValueError(
        f"Unknown Services-tab sidebar item source: "
        f"routine {routine_name!r} has source {source!r}"
    )


def _services_panel_key_for_item(
    item: object, routine_origins: Mapping[str, Any] | None = None
) -> ServicesPanelKey:
    """Return the panel that renders ``item``.

    ``ServiceProcItem`` and ``BgCmdItem`` (oneshots) belong to the Service
    Procs panel; ``LumberjackItem`` and ``ChopItem`` resolve through the
    cached parent routine origin (missing origins fall back to User so
    degraded seeds stay visible). Raises :class:`TypeError` for unknown
    item types and :class:`ValueError` for unknown source values so a
    new item type or source value fails loudly instead of silently
    landing in the wrong panel.
    """
    class_name = type(item).__name__
    if class_name in _SERVICE_PROCS_ITEM_CLASSES:
        return "service_procs"
    if class_name in _ROUTINE_ITEM_CLASSES:
        routine_name = _routine_name_for_item(item)
        source = _source_for_routine(routine_name, routine_origins)
        return routine_panel_key_for_source(source)
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

    def visible_keys(self) -> list[ServicesPanelKey]:
        """Return the ordered panel keys that should be rendered.

        Service Procs is always visible (with its empty placeholder).
        Each routine panel is visible only when it holds at least one
        row, except that an entirely routine-free sidebar still shows
        the User Routines panel with the add hint as the empty state.
        """
        visible: list[ServicesPanelKey] = ["service_procs"]
        has_any_routine = any(
            self.panels.get(key, _ServicesPanelSlice()).global_indices
            for key in ROUTINE_PANEL_ORDER
        )
        for key in ROUTINE_PANEL_ORDER:
            if self.panels.get(key, _ServicesPanelSlice()).global_indices:
                visible.append(key)
        if not has_any_routine and "user_routines" not in visible:
            visible.append("user_routines")
        ordered = [key for key in SERVICES_PANEL_ORDER if key in visible]
        return ordered

    def first_visible_routine_panel(self) -> ServicesPanelKey | None:
        """Return the first visible routine panel, if any.

        The global scheduler stopped/unavailable badge renders on this
        panel only so it never repeats across sections.
        """
        for key in self.visible_keys():
            if key in ROUTINE_PANEL_ORDER:
                return key
        return None


def build_services_panel_index(
    items: Sequence[object],
    routine_origins: Mapping[str, Any] | None = None,
) -> ServicesPanelIndex:
    """Build a :class:`ServicesPanelIndex` over ``items`` in visual order."""
    panels: dict[ServicesPanelKey, _ServicesPanelSlice] = {}
    for global_idx, item in enumerate(items):
        key = _services_panel_key_for_item(item, routine_origins)
        slot = panels.get(key)
        if slot is None:
            slot = _ServicesPanelSlice()
            panels[key] = slot
        slot.global_to_local[global_idx] = len(slot.items)
        slot.items.append(item)
        slot.global_indices.append(global_idx)
    return ServicesPanelIndex(panels=panels)
