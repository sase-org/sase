"""Central Agents-panel fold-scope selection and reconciliation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ...models.agent_group_fold import AgentPanelFoldScope, GroupKey
    from ...models.agent_panels import PanelKey
    from ...models.group_fold import GroupFoldRegistry


def panel_fold_registry(
    owner: Any,
    panel_key: PanelKey,
) -> GroupFoldRegistry | Any:
    """Resolve the ordinary fold registry for one rendered Agents panel.

    Direct mixin tests and older embedding callers may still install a plain
    registry.  Those already represent one tree and are returned unchanged.
    """
    from ...models.agent_group_fold import AgentGroupFoldRegistry

    registry_owner = getattr(owner, "_group_fold_registry", None)
    if isinstance(registry_owner, AgentGroupFoldRegistry):
        return registry_owner.for_panel(
            panel_key,
            merged=bool(getattr(owner, "_agent_panels_grouped", False)),
        )
    return registry_owner


def focused_panel_fold_registry(owner: Any) -> GroupFoldRegistry | Any:
    """Resolve the ordinary fold registry for the currently focused panel."""
    panel_group = getattr(owner, "_panel_group", None)
    panel_key = panel_group.focused_key if panel_group is not None else None
    return panel_fold_registry(owner, panel_key)


def panel_fold_version_signature(
    owner: Any,
    panel_keys: Iterable[PanelKey],
) -> tuple[Any, ...]:
    """Return a cache signature covering every currently rendered panel."""
    from ...models.agent_group_fold import AgentGroupFoldRegistry

    registry_owner = getattr(owner, "_group_fold_registry", None)
    keys = tuple(panel_keys)
    if isinstance(registry_owner, AgentGroupFoldRegistry):
        return registry_owner.layout_version_signature(
            keys,
            merged=bool(getattr(owner, "_agent_panels_grouped", False)),
        )
    return (
        id(registry_owner),
        getattr(registry_owner, "version", 0),
    )


def reconcile_panel_fold_registries(
    owner: Any,
    known_by_scope: Mapping[AgentPanelFoldScope, Iterable[GroupKey]],
) -> None:
    """Prune the active layout's scoped registries from a prepared projection."""
    from ...models.agent_group_fold import AgentGroupFoldRegistry

    registry_owner = getattr(owner, "_group_fold_registry", None)
    merged = bool(getattr(owner, "_agent_panels_grouped", False))
    panel_state_changed = False
    collapsed_panels = getattr(owner, "_collapsed_panel_keys", None)
    if not merged and collapsed_panels is not None:
        known_panels = {scope.panel_key for scope in known_by_scope if not scope.merged}
        before = len(collapsed_panels)
        collapsed_panels.intersection_update(known_panels)
        panel_state_changed = len(collapsed_panels) != before
    if isinstance(registry_owner, AgentGroupFoldRegistry):
        group_state_changed = registry_owner.reconcile_layout(
            known_by_scope, merged=merged
        )
        if panel_state_changed or group_state_changed:
            schedule = getattr(owner, "_agents_fold_state_changed", None)
            if callable(schedule):
                schedule()
        return

    # Compatibility for focused tests/embedders that still expose one plain
    # registry: retain the historical cross-panel union behavior there.
    clear_unknown = getattr(registry_owner, "clear_unknown", None)
    if callable(clear_unknown):
        changed = clear_unknown(
            key
            for scope, keys in known_by_scope.items()
            if scope.merged == merged
            for key in cast("Iterable[GroupKey]", keys)
        )
        if panel_state_changed or changed:
            schedule = getattr(owner, "_agents_fold_state_changed", None)
            if callable(schedule):
                schedule()
