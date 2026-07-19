"""Shared whole-panel fold intent and effective-state helpers."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey


def effective_panel_collapses(
    owner: Any,
    panel_keys: Collection[PanelKey] | None = None,
) -> set[PanelKey]:
    """Return effective collapse state for a split Agents-panel collection."""
    if bool(getattr(owner, "_agent_panels_grouped", False)):
        return set()
    from ...models.tribe_display import effective_collapsed_panel_keys

    return effective_collapsed_panel_keys(
        panel_keys,
        collapsed_intent=getattr(owner, "_collapsed_panel_keys", ()),
        expanded_intent=getattr(owner, "_expanded_panel_keys", ()),
    )


def panel_is_collapsed(owner: Any, panel_key: PanelKey) -> bool:
    """Return whether one panel is effectively collapsed."""
    return panel_key in effective_panel_collapses(owner, (panel_key,))


def set_panel_fold_intent(
    owner: Any,
    panel_key: PanelKey,
    *,
    collapsed: bool,
) -> None:
    """Record one explicit, disjoint expand/collapse intent in memory."""
    collapsed_keys = getattr(owner, "_collapsed_panel_keys", None)
    if collapsed_keys is None:
        collapsed_keys = set()
        owner._collapsed_panel_keys = collapsed_keys
    expanded_keys = getattr(owner, "_expanded_panel_keys", None)
    if expanded_keys is None:
        expanded_keys = set()
        owner._expanded_panel_keys = expanded_keys
    if collapsed:
        collapsed_keys.add(panel_key)
        expanded_keys.discard(panel_key)
    else:
        collapsed_keys.discard(panel_key)
        expanded_keys.add(panel_key)


def clear_panel_fold_intents(owner: Any) -> None:
    """Clear every explicit whole-panel fold intent."""
    collapsed = getattr(owner, "_collapsed_panel_keys", None)
    if collapsed is not None:
        collapsed.clear()
    expanded = getattr(owner, "_expanded_panel_keys", None)
    if expanded is not None:
        expanded.clear()


__all__ = [
    "clear_panel_fold_intents",
    "effective_panel_collapses",
    "panel_is_collapsed",
    "set_panel_fold_intent",
]
