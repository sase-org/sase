"""Shared per-pane grouping-mode and fold-registry mixin for Artifacts panes.

Files, Plans/Documents, and Stitches all bucket their already-loaded rows by
one declared :class:`PaneGroupingModeDecl` at a time.  This mixin owns the
mode-cycling and per-mode :class:`GroupFoldRegistry` bookkeeping that's
identical across those panes; each host pane supplies only the two things
that differ — how to rebuild its grouped rows for a given registry, and how
to refresh its OptionList with a preferred selection afterward.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import (
    ArtifactGroupBuildResult,
    group_banner_target,
    is_group_banner_target,
)
from ...models.group_fold import GroupFoldRegistry, GroupKey
from .entry_navigation import ArtifactEntryTarget

if TYPE_CHECKING:
    from ..._artifact_tab_model import ArtifactsPaneContract


class ArtifactGroupFoldMixin:
    """Own active grouping mode, per-mode fold registries, and fold actions."""

    contract: ArtifactsPaneContract | None
    _group_fold_registries: dict[str, GroupFoldRegistry]
    _active_group_mode_id: str | None

    if TYPE_CHECKING:

        def _group_pane_id(self) -> str: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def _group_build_result(
            self,
            *,
            fold_registry: GroupFoldRegistry,
        ) -> ArtifactGroupBuildResult: ...

        def _group_refresh(
            self,
            preferred_target: ArtifactEntryTarget | None,
        ) -> None: ...

    def _init_group_fold(self) -> None:
        self._group_fold_registries = {}
        self._active_group_mode_id = None

    def _grouping_modes(self) -> tuple[PaneGroupingModeDecl, ...]:
        contract = self.contract
        return () if contract is None else contract.grouping.modes

    def _active_grouping_mode(self) -> PaneGroupingModeDecl | None:
        modes = self._grouping_modes()
        if not modes:
            return None
        if self._active_group_mode_id is None:
            contract = self.contract
            default = contract.grouping.default_mode if contract is not None else None
            self._active_group_mode_id = default or modes[0].id
        return next(
            (mode for mode in modes if mode.id == self._active_group_mode_id),
            modes[0],
        )

    def _group_fold_registry(self) -> GroupFoldRegistry:
        mode = self._active_grouping_mode()
        mode_id = mode.id if mode is not None else "_default"
        registry = self._group_fold_registries.get(mode_id)
        if registry is None:
            registry = GroupFoldRegistry()
            self._group_fold_registries[mode_id] = registry
        return registry

    def _focused_group_key(self) -> GroupKey | None:
        """Return the group key ``h``/``l`` should act on for the selection."""
        target = self.selected_entry_target()
        if target is None:
            return None
        if is_group_banner_target(target):
            return tuple(target.parts[2:])
        registry = self._group_fold_registry()
        result = self._group_build_result(fold_registry=registry)
        deepest: GroupKey | None = None
        deepest_level = -1
        for row in result.rows:
            if row.kind != "banner" or row.banner is None:
                continue
            if target in row.banner.member_targets and row.banner.level > deepest_level:
                deepest = row.banner.group_key
                deepest_level = row.banner.level
        return deepest

    def expand_fold_for_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Expand the collapsed banners whose members include *target*."""
        registry = self._group_fold_registry()
        result = self._group_build_result(fold_registry=registry)
        changed = False
        for row in result.rows:
            if (
                row.kind == "banner"
                and row.banner is not None
                and row.banner.collapsed
                and target in row.banner.member_targets
            ):
                if registry.expand(row.banner.group_key):
                    changed = True
        if changed:
            self._group_refresh(target)
        return changed

    def _group_banner_target(self, group_key: GroupKey) -> ArtifactEntryTarget | None:
        mode = self._active_grouping_mode()
        if mode is None:
            return None
        return group_banner_target(self._group_pane_id(), mode.id, group_key)

    def group_fold_expand(self) -> bool:
        """Expand the focused collapsed banner (``l`` action)."""
        target = self.selected_entry_target()
        if not is_group_banner_target(target):
            return False
        assert target is not None
        group_key = tuple(target.parts[2:])
        registry = self._group_fold_registry()
        if not registry.expand(group_key):
            return False
        result = self._group_build_result(fold_registry=registry)
        preferred = target
        for row in result.rows:
            if (
                row.kind == "banner"
                and row.banner is not None
                and row.banner.group_key == group_key
            ):
                if row.banner.member_targets:
                    preferred = row.banner.member_targets[0]
                break
        self._group_refresh(preferred)
        return True

    def group_fold_collapse(self) -> bool:
        """Collapse the focused banner, or the selected row's group (``h``)."""
        registry = self._group_fold_registry()
        target = self.selected_entry_target()
        if is_group_banner_target(target):
            assert target is not None
            group_key = tuple(target.parts[2:])
            if len(group_key) > 1 and registry.is_collapsed(group_key):
                parent_key = group_key[:-1]
                if not registry.collapse(parent_key):
                    return False
                self._group_refresh(self._group_banner_target(parent_key))
                return True
            if not registry.collapse(group_key):
                return False
            self._group_refresh(self._group_banner_target(group_key))
            return True

        deep_key = self._focused_group_key()
        if deep_key is None:
            return False
        if not registry.collapse(deep_key):
            return False
        self._group_refresh(self._group_banner_target(deep_key))
        return True

    def group_fold_expand_all(self) -> bool:
        """Peel one collapsed layer at the currently visible level (``L``)."""
        registry = self._group_fold_registry()
        result = self._group_build_result(fold_registry=registry)
        changed = False
        for row in result.rows:
            if row.kind == "banner" and row.banner is not None and row.banner.collapsed:
                if registry.expand(row.banner.group_key):
                    changed = True
        if changed:
            self._group_refresh(self.selected_entry_target())
        return changed

    def group_fold_collapse_all(self) -> bool:
        """Collapse the deepest expanded visible banner level (``H``)."""
        registry = self._group_fold_registry()
        result = self._group_build_result(fold_registry=registry)
        levels = [
            row.banner.level
            for row in result.rows
            if row.kind == "banner"
            and row.banner is not None
            and not row.banner.collapsed
        ]
        if not levels:
            return False
        deepest = max(levels)
        changed = False
        for row in result.rows:
            if (
                row.kind == "banner"
                and row.banner is not None
                and row.banner.level == deepest
                and not row.banner.collapsed
            ):
                if registry.collapse(row.banner.group_key):
                    changed = True
        if changed:
            self._group_refresh(self.selected_entry_target())
        return changed

    def group_cycle_mode(self, *, reverse: bool = False) -> bool:
        """Advance the active grouping mode (``o``/reverse ``o``)."""
        modes = self._grouping_modes()
        if len(modes) < 2:
            return False
        current = self._active_grouping_mode()
        ids = [mode.id for mode in modes]
        index = ids.index(current.id) if current is not None else 0
        self._active_group_mode_id = ids[(index + (-1 if reverse else 1)) % len(ids)]
        previous = self.selected_entry_target()
        preferred = (
            None if previous is None or is_group_banner_target(previous) else previous
        )
        self._group_refresh(preferred)
        return True


__all__ = ["ArtifactGroupFoldMixin"]
