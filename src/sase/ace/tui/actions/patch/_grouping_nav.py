"""Grouped-mode navigation, folding, and jump-hint helpers for the Patches pane.

The Patches pane is always grouped (``BY_PROJECT`` / ``BY_DATE`` /
``BY_STATUS``).  The actions in
:mod:`sase.ace.tui.actions.navigation._basic` and
:mod:`sase.ace.tui.actions.agents._folding` delegate the PR branch into
this mixin so banner rows are first-class navigation/fold targets,
mirroring the Agents-tab mental model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.patch_groups import (
    PatchGroupingMode,
    build_patch_tree,
    enumerate_patch_group_keys,
)

if TYPE_CHECKING:
    from ....patch import Patch
    from ...models.group_fold import GroupFoldRegistry, GroupKey


TabName = Literal["artifacts", "agents", "axe"]


# Banner stops are ``("banner", group_key)`` and PR stops are
# ``("patch", filtered_idx)``.  Filtered_idx is the index into
# ``self.patches`` (post-filter), matching ``current_idx``.
_NavigationStop = tuple[Literal["banner", "patch"], object]


class PatchGroupingNavMixin:
    """Mixin providing grouped-mode navigation/fold/jump helpers for Patches."""

    # Type hints for attributes accessed from AceApp.
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    _patch_grouping_mode: PatchGroupingMode
    _patch_group_fold_registry: GroupFoldRegistry
    _current_patch_group_key: tuple[str, ...] | None

    def _patch_navigation_stops(self) -> list[_NavigationStop]:
        """Return the Patch list's selectable rows in render order.

        Each entry is ``("patch", idx)`` for a visible Patch row or
        ``("banner", group_key)`` for a collapsed banner row.  Used by
        ``j``/``k`` so the cursor steps through every visible row,
        including collapsed banners.
        """
        if not self.patches:
            return []
        registry = getattr(self, "_patch_group_fold_registry", None)
        mode: PatchGroupingMode = self._patch_grouping_mode
        tree = build_patch_tree(self.patches, mode=mode, fold_registry=registry)
        stops: list[_NavigationStop] = []
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    stops.append(("banner", entry.group.group_key))
            elif entry.kind == "patch" and entry.patch_idx is not None:
                stops.append(("patch", entry.patch_idx))
        return stops

    def _focused_patch_group_keys(
        self,
    ) -> tuple[GroupKey | None, GroupKey | None]:
        """Return ``(deep_key | None, l0_key | None)`` for the focused Patch.

        ``deep_key`` is the deepest banner that contains the focused PR —
        the L1 sibling-root banner when one is visible, otherwise
        ``None``.  ``l0_key`` is the enclosing project / date / status
        banner.  Returns ``(None, None)`` when no PR is focused.
        """
        from ...models.group_fold import GroupFoldRegistry

        if not self.patches or not (0 <= self.current_idx < len(self.patches)):
            return (None, None)
        # Build with an empty registry so collapsed banners don't hide
        # the agent — we want every enclosing banner the renderer would
        # emit at full expansion.
        entries = build_patch_tree(
            self.patches,
            mode=self._patch_grouping_mode,
            fold_registry=GroupFoldRegistry(),
        )
        l0: GroupKey | None = None
        deep: GroupKey | None = None
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if self.current_idx not in entry.group.patch_indices:
                continue
            if entry.group.level == 0:
                l0 = entry.group.group_key
            else:
                deep = entry.group.group_key
        return (deep, l0)

    def _navigate_patch_panel(self, direction: int) -> None:
        """Step ``current_idx``/``_current_patch_group_key`` by one stop.

        The active stops list mirrors what the renderer is drawing, so
        ``j``/``k`` walks the same sequence the user sees, including
        collapsed banner rows.
        """
        stops = self._patch_navigation_stops()
        if not stops:
            return
        old_idx = self.current_idx
        old_key = self._current_patch_group_key
        pos: int | None = None
        if old_key is not None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "banner" and payload == old_key:
                    pos = i
                    break
        if pos is None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "patch" and payload == old_idx:
                    pos = i
                    break
        if pos is None:
            # No prior anchor matches; fall back to the closest PR stop
            # by global index, otherwise the first banner.
            best: int | None = None
            best_dist: int | None = None
            for i, (kind, payload) in enumerate(stops):
                if kind != "patch":
                    continue
                assert isinstance(payload, int)
                dist = abs(payload - old_idx)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = i
            pos = best if best is not None else 0
        new_pos = (pos + direction) % len(stops)
        kind, payload = stops[new_pos]
        if kind == "banner":
            assert isinstance(payload, tuple)
            self._current_patch_group_key = payload
        else:
            assert isinstance(payload, int)
            self._current_patch_group_key = None
            self.current_idx = payload
        # The ``current_idx`` setter only fires ``watch_current_idx``
        # (the refresh trigger) when the index actually changes.
        # Banner-targeted stops leave ``current_idx`` untouched, and
        # banner→Patch transitions can land on the same index — in both
        # cases nothing fires a refresh, so the highlight stays stale
        # on the previously selected row.  Drive it explicitly whenever
        # only ``_current_patch_group_key`` changed.
        if self.current_idx == old_idx and self._current_patch_group_key != old_key:
            self._refresh_display()  # type: ignore[attr-defined]

    def _snap_patch_focus_after_fold_change(self) -> None:
        """Re-anchor focus when the active PR or banner stopped being visible.

        After collapsing the enclosing group of the focused Patch, the
        renderer hides the Patch's row.  Snap focus to the deepest
        collapsed ancestor banner that's still visible so the cursor
        lands on a row the user can actually see.
        """
        if not self.patches:
            self._current_patch_group_key = None
            return
        registry = self._patch_group_fold_registry
        entries = build_patch_tree(
            self.patches,
            mode=self._patch_grouping_mode,
            fold_registry=registry,
        )
        # If the focused Patch row is in the visible tree, focus stays on it.
        for entry in entries:
            if entry.kind == "patch" and entry.patch_idx == self.current_idx:
                self._current_patch_group_key = None
                return
        # Otherwise pick the deepest collapsed ancestor banner.
        best_key: GroupKey | None = None
        best_level = -1
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            g = entry.group
            if not g.is_collapsed:
                continue
            if self.current_idx not in g.patch_indices:
                continue
            if g.level > best_level:
                best_level = g.level
                best_key = g.group_key
        if best_key is not None:
            self._current_patch_group_key = best_key

    def _reanchor_after_patch_banner_expansion(self, expanded_key: GroupKey) -> None:
        """Move focus off a banner that just stopped being selectable.

        Picks (in order): the first remaining collapsed child banner of
        the expanded group, then the first visible PR of the group, then
        leaves selection alone.
        """
        registry = self._patch_group_fold_registry
        entries = build_patch_tree(
            self.patches,
            mode=self._patch_grouping_mode,
            fold_registry=registry,
        )
        expanded_indices: tuple[int, ...] = ()
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.group_key == expanded_key:
                    expanded_indices = entry.group.patch_indices
                    break
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            g = entry.group
            if (
                len(g.group_key) > len(expanded_key)
                and g.group_key[: len(expanded_key)] == expanded_key
                and g.is_collapsed
            ):
                self._current_patch_group_key = g.group_key
                return
        for entry in entries:
            if entry.kind == "patch" and entry.patch_idx is not None:
                if entry.patch_idx in expanded_indices:
                    self._current_patch_group_key = None
                    self.current_idx = entry.patch_idx
                    return
        self._current_patch_group_key = None

    def _expand_patch_group_fold(self) -> bool:
        """Expand the focused banner's group (``l`` action).

        Returns ``True`` when the registry actually changed so callers
        only refresh the display when something moved.
        """
        registry = self._patch_group_fold_registry
        if self._current_patch_group_key is not None:
            key: GroupKey = tuple(self._current_patch_group_key)
            if registry.expand(key):
                self._reanchor_after_patch_banner_expansion(key)
                return True
            return False
        # Agent focus, no banner — there's nothing collapsed to expand
        # at this level (the focused PR is in an already-expanded group).
        return False

    def _collapse_patch_group_fold(self) -> bool:
        """Collapse the focused banner or the focused Patch's enclosing group.

        ``h`` rules:

        * Banner focus on an L1 sibling-root that's already collapsed →
          escalate to the parent project/date/status banner.
        * Banner focus on any other already-collapsed banner → no-op.
        * Banner focus on an expanded banner → collapse it.
        * Agent focus → collapse the deepest enclosing group (L1 if
          present, else L0) and snap focus to its now-visible banner.
        """
        registry = self._patch_group_fold_registry
        if self._current_patch_group_key is not None:
            cur_key: GroupKey = tuple(self._current_patch_group_key)
            if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                parent_key: GroupKey = cur_key[:-1]
                if registry.collapse(parent_key):
                    self._current_patch_group_key = parent_key
                    return True
                return False
            if registry.collapse(cur_key):
                return True
            return False

        deep_key, l0_key = self._focused_patch_group_keys()
        target = deep_key or l0_key
        if target is None:
            return False
        if registry.collapse(target):
            self._current_patch_group_key = target
            self._snap_patch_focus_after_fold_change()
            return True
        return False

    def _expand_all_patch_group_folds(self) -> bool:
        """``L`` action: peel one fold layer at the visible-tree level.

        Snapshots the currently-visible entries, then expands every
        collapsed banner in that snapshot.  Rows that become visible *as
        a result of* this press are not stepped — repeated presses peel
        one layer at a time.
        """
        registry = self._patch_group_fold_registry
        entries = build_patch_tree(
            self.patches,
            mode=self._patch_grouping_mode,
            fold_registry=registry,
        )
        changed = False
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    if registry.expand(entry.group.group_key):
                        changed = True
        if changed:
            self._current_patch_group_key = None
        return changed

    def _collapse_all_patch_group_folds(self) -> bool:
        """``H`` action: collapse the deepest expanded visible banner level.

        Snapshots the visible tree and collapses expanded banner rows
        only at the deepest expanded level in that snapshot.  Banners
        hidden behind an already-collapsed ancestor are skipped
        (snapshot-at-start rule); the next ``H`` press picks up the
        next visible level.
        """
        registry = self._patch_group_fold_registry
        entries = build_patch_tree(
            self.patches,
            mode=self._patch_grouping_mode,
            fold_registry=registry,
        )
        changed = False
        deepest_expanded_group_level = max(
            (
                entry.group.level
                for entry in entries
                if entry.kind == "group"
                and entry.group is not None
                and not entry.group.is_collapsed
            ),
            default=None,
        )
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if entry.group.level != deepest_expanded_group_level:
                continue
            if not entry.group.is_collapsed:
                if registry.collapse(entry.group.group_key):
                    changed = True
        if changed:
            self._snap_patch_focus_after_fold_change()
        return changed

    def _patch_jump_targets(
        self,
    ) -> list[tuple[Literal["patch", "banner"], object]]:
        """Return jump targets for the Patches pane in render order.

        Mirrors the ``j``/``k`` stops list but is named separately so
        the call site can stay close to other jump-mode helpers.
        Collapsed banners contribute ``("banner", group_key)`` entries;
        expanded banners are non-selectable and excluded.
        """
        return list(self._patch_navigation_stops())

    def _patch_banner_focus_still_valid(self) -> bool:
        """Return ``True`` when the active banner key still maps to a banner.

        Used after a Patch list reload: if the user was focused on a banner
        whose group was filtered out (e.g. query change dropped its
        last member), drop the stale focus so the cursor falls back to
        a real Patch row.  Tolerant of partially-initialized fixtures: a
        harness that never assigned ``_current_patch_group_key``
        is treated as "no banner focused" (valid).
        """
        key = getattr(self, "_current_patch_group_key", None)
        if key is None:
            return True
        keys = enumerate_patch_group_keys(self.patches, mode=self._patch_grouping_mode)
        return tuple(key) in {tuple(k) for k in keys}
