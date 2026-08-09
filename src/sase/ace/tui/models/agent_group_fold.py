"""Panel-scoped fold registries for the Agents-tab grouping trees.

Each group key is an arbitrary-length ``tuple[str, ...]``. Common shapes:

* ``(project,)`` for an L0 project banner;
* ``(project, patch)`` for an L1 Patch banner (3-level mode)
  or ``(project, name_root)`` for an L1 name-root banner (2-level
  fallback);
* ``(project, patch, name_root)`` for an L2 name-root banner in
  3-level mode;
* ``(*parent_key, name_root, name_prefix)`` for dotted-name prefix
  subgroups such as ``("Done", "sase-42", "sase-42.2")``.

Every rendered Agents panel builds an independent grouping tree, so equal
local keys in different panels must not share collapse state.  The
:class:`AgentGroupFoldRegistry` owns one neutral
:class:`~sase.ace.tui.models.group_fold.GroupFoldRegistry` per explicit
panel scope.  The scope also includes the split/merged layout bit because
the split ``@default`` panel and the merged ``All agents`` panel both use a
``None`` panel key.

This registry layers *above* the existing per-workflow
:class:`FoldStateManager`: workflow-level folds only matter once the
group containing the workflow is expanded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .group_fold import GroupFoldRegistry, GroupKey
from .agent_panels import PanelKey

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_groups import GroupingMode


@dataclass(frozen=True)
class AgentPanelFoldScope:
    """Identity of one rendered Agents-panel grouping tree."""

    panel_key: PanelKey
    merged: bool = False


@dataclass(frozen=True)
class AgentPanelFoldSnapshot:
    """Immutable collapse state for one rendered Agents-panel tree."""

    scope: AgentPanelFoldScope
    collapsed: frozenset[GroupKey]


@dataclass
class AgentGroupFoldRegistry:
    """Own one ordinary fold registry for every Agents panel scope.

    Tree builders must receive the value returned by :meth:`for_panel`,
    never this owner itself.  The unscoped methods/properties delegate to
    the split ``@default`` scope for compatibility with focused model tests and
    older callers; production Agents paths resolve a scope explicitly.
    """

    _registries: dict[AgentPanelFoldScope, GroupFoldRegistry] = field(
        default_factory=dict
    )

    def for_panel(
        self,
        panel_key: PanelKey,
        *,
        merged: bool = False,
    ) -> GroupFoldRegistry:
        """Return the ordinary registry for one rendered panel tree."""
        scope = AgentPanelFoldScope(panel_key=panel_key, merged=merged)
        registry = self._registries.get(scope)
        if registry is None:
            registry = GroupFoldRegistry()
            self._registries[scope] = registry
        return registry

    def reconcile_layout(
        self,
        known_by_scope: Mapping[AgentPanelFoldScope, Iterable[GroupKey]],
        *,
        merged: bool,
    ) -> bool:
        """Prune stale folds independently for the active panel layout.

        Scopes from other grouping modes live in other owners, while scopes
        from the inactive split/merged layout remain untouched here.  Active
        scopes whose panels disappeared are removed entirely.
        """
        changed = False
        active_scopes = {scope for scope in known_by_scope if scope.merged == merged}
        for scope in list(self._registries):
            if scope.merged == merged and scope not in active_scopes:
                if self._registries[scope].collapsed:
                    changed = True
                del self._registries[scope]
        for scope in active_scopes:
            if self.for_panel(scope.panel_key, merged=scope.merged).clear_unknown(
                known_by_scope[scope]
            ):
                changed = True
        return changed

    def snapshot(self) -> tuple[AgentPanelFoldSnapshot, ...]:
        """Return immutable, non-empty per-panel collapse snapshots."""
        return tuple(
            AgentPanelFoldSnapshot(scope=scope, collapsed=registry.snapshot())
            for scope, registry in self._registries.items()
            if registry.collapsed
        )

    def restore(self, snapshots: Iterable[AgentPanelFoldSnapshot]) -> None:
        """Replace all panel registries from persistence snapshots.

        New :class:`GroupFoldRegistry` objects are allocated even when the
        logical state happens to match. Their identities therefore invalidate
        cache signatures that include ``id(registry)``.
        """
        restored: dict[AgentPanelFoldScope, GroupFoldRegistry] = {}
        for snapshot in snapshots:
            registry = GroupFoldRegistry()
            registry.restore(snapshot.collapsed)
            restored[snapshot.scope] = registry
        self._registries = restored

    def layout_version_signature(
        self,
        panel_keys: Iterable[PanelKey],
        *,
        merged: bool = False,
    ) -> tuple[tuple[PanelKey, int, int], ...]:
        """Return a cheap cache signature for all rendered panel views."""
        return tuple(
            (key, id(registry), registry.version)
            for key in panel_keys
            for registry in (self.for_panel(key, merged=merged),)
        )

    @property
    def collapsed(self) -> set[GroupKey]:
        """Return the union of collapsed keys (compatibility/debug view)."""
        collapsed: set[GroupKey] = set()
        for registry in self._registries.values():
            collapsed.update(registry.collapsed)
        return collapsed

    @property
    def version(self) -> int:
        """Return an aggregate version for compatibility/debug consumers."""
        return sum(registry.version for registry in self._registries.values())

    def is_collapsed(self, key: GroupKey) -> bool:
        return self.for_panel(None).is_collapsed(key)

    def collapse(self, key: GroupKey) -> bool:
        return self.for_panel(None).collapse(key)

    def expand(self, key: GroupKey) -> bool:
        return self.for_panel(None).expand(key)

    def collapse_keys(self, keys: Iterable[GroupKey]) -> bool:
        return self.for_panel(None).collapse_keys(keys)

    def expand_keys(self, keys: Iterable[GroupKey]) -> bool:
        return self.for_panel(None).expand_keys(keys)

    def clear_unknown(self, known: Iterable[GroupKey]) -> bool:
        return self.for_panel(None).clear_unknown(known)


def enumerate_panel_group_keys(
    agents: list[Agent],
    *,
    mode: GroupingMode,
    merged: bool = False,
) -> dict[AgentPanelFoldScope, list[GroupKey]]:
    """Return the grouping keys rendered independently in every panel.

    Imports stay local to keep this state-owner module free of the grouping
    tree's heavier model dependencies at import time.
    """
    from .agent_groups import enumerate_group_keys
    from .agent_panels import AgentPanelGroup, agents_for_panel

    panel_group = AgentPanelGroup.from_agents(
        agents,
        merge_tribe_panels=merged,
    )
    return {
        AgentPanelFoldScope(panel_key=panel_key, merged=merged): enumerate_group_keys(
            agents_for_panel(
                agents,
                panel_key,
                merge_tribe_panels=merged,
            ),
            mode=mode,
        )
        for panel_key in panel_group.panel_keys
    }


__all__ = [
    "AgentGroupFoldRegistry",
    "AgentPanelFoldSnapshot",
    "AgentPanelFoldScope",
    "GroupFoldRegistry",
    "GroupKey",
    "enumerate_panel_group_keys",
]
