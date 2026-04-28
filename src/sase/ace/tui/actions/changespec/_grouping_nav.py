"""Grouped-mode navigation, folding, and jump-hint helpers for the CLs tab.

These helpers are no-ops while ``_changespec_grouping_mode`` is ``FLAT`` —
the legacy direct-index code path keeps owning the CLs tab in that mode
so existing flat-mode behavior stays exactly as it was.  When the user
cycles into a grouped mode, the actions in
:mod:`sase.ace.tui.actions.navigation._basic` and
:mod:`sase.ace.tui.actions.agents._folding` delegate the CL branch into
this mixin so banner rows become first-class navigation/fold targets,
mirroring the Agents-tab mental model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.changespec_groups import (
    ChangeSpecGroupingMode,
    build_changespec_tree,
    enumerate_changespec_group_keys,
)

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...models.group_fold import GroupFoldRegistry, GroupKey


TabName = Literal["changespecs", "agents", "axe"]


# Banner stops are ``("banner", group_key)`` and CL stops are
# ``("changespec", filtered_idx)``.  Filtered_idx is the index into
# ``self.changespecs`` (post-filter), matching ``current_idx``.
_NavigationStop = tuple[Literal["banner", "changespec"], object]


class ChangeSpecGroupingNavMixin:
    """Mixin providing grouped-mode navigation/fold/jump helpers for CLs."""

    # Type hints for attributes accessed from AceApp.
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    _changespec_grouping_mode: ChangeSpecGroupingMode
    _changespec_group_fold_registry: GroupFoldRegistry
    _current_changespec_group_key: tuple[str, ...] | None

    def _changespec_grouping_active(self) -> bool:
        """Return ``True`` when grouped mode owns the CL list rendering."""
        mode = getattr(self, "_changespec_grouping_mode", ChangeSpecGroupingMode.FLAT)
        return mode is not ChangeSpecGroupingMode.FLAT

    def _changespec_navigation_stops(self) -> list[_NavigationStop]:
        """Return the CL list's selectable rows in render order.

        Each entry is ``("changespec", idx)`` for a visible CL row or
        ``("banner", group_key)`` for a collapsed banner row.  Used by
        ``j``/``k`` so the cursor steps through every visible row,
        including collapsed banners.

        Returns ``[]`` while flat mode is active so callers fall back
        to the legacy direct-index path.
        """
        if not self._changespec_grouping_active() or not self.changespecs:
            return []
        registry = getattr(self, "_changespec_group_fold_registry", None)
        mode: ChangeSpecGroupingMode = self._changespec_grouping_mode
        tree = build_changespec_tree(
            self.changespecs, mode=mode, fold_registry=registry
        )
        stops: list[_NavigationStop] = []
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    stops.append(("banner", entry.group.group_key))
            elif entry.kind == "changespec" and entry.changespec_idx is not None:
                stops.append(("changespec", entry.changespec_idx))
        return stops

    def _focused_changespec_group_keys(
        self,
    ) -> tuple[GroupKey | None, GroupKey | None]:
        """Return ``(deep_key | None, l0_key | None)`` for the focused CL.

        ``deep_key`` is the deepest banner that contains the focused CL —
        the L1 sibling-root banner when one is visible, otherwise
        ``None``.  ``l0_key`` is the enclosing project / date / status
        banner.  Returns ``(None, None)`` while flat mode is active or
        when no CL is focused.
        """
        from ...models.group_fold import GroupFoldRegistry

        if not self._changespec_grouping_active():
            return (None, None)
        if not self.changespecs or not (0 <= self.current_idx < len(self.changespecs)):
            return (None, None)
        # Build with an empty registry so collapsed banners don't hide
        # the agent — we want every enclosing banner the renderer would
        # emit at full expansion.
        entries = build_changespec_tree(
            self.changespecs,
            mode=self._changespec_grouping_mode,
            fold_registry=GroupFoldRegistry(),
        )
        l0: GroupKey | None = None
        deep: GroupKey | None = None
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if self.current_idx not in entry.group.changespec_indices:
                continue
            if entry.group.level == 0:
                l0 = entry.group.group_key
            else:
                deep = entry.group.group_key
        return (deep, l0)

    def _navigate_changespec_panel(self, direction: int) -> None:
        """Step ``current_idx``/``_current_changespec_group_key`` by one stop.

        The active stops list mirrors what the renderer is drawing, so
        ``j``/``k`` walks the same sequence the user sees, including
        collapsed banner rows.
        """
        stops = self._changespec_navigation_stops()
        if not stops:
            return
        old_idx = self.current_idx
        old_key = self._current_changespec_group_key
        pos: int | None = None
        if old_key is not None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "banner" and payload == old_key:
                    pos = i
                    break
        if pos is None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "changespec" and payload == old_idx:
                    pos = i
                    break
        if pos is None:
            # No prior anchor matches; fall back to the closest CL stop
            # by global index, otherwise the first banner.
            best: int | None = None
            best_dist: int | None = None
            for i, (kind, payload) in enumerate(stops):
                if kind != "changespec":
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
            self._current_changespec_group_key = payload
        else:
            assert isinstance(payload, int)
            self._current_changespec_group_key = None
            self.current_idx = payload
        # The ``current_idx`` setter only fires ``watch_current_idx``
        # (the refresh trigger) when the index actually changes.
        # Banner-targeted stops leave ``current_idx`` untouched, and
        # banner→CL transitions can land on the same index — in both
        # cases nothing fires a refresh, so the highlight stays stale
        # on the previously selected row.  Drive it explicitly whenever
        # only ``_current_changespec_group_key`` changed.
        if (
            self.current_idx == old_idx
            and self._current_changespec_group_key != old_key
        ):
            self._refresh_display()  # type: ignore[attr-defined]

    def _snap_changespec_focus_after_fold_change(self) -> None:
        """Re-anchor focus when the active CL or banner stopped being visible.

        After collapsing the enclosing group of the focused CL, the
        renderer hides the CL's row.  Snap focus to the deepest
        collapsed ancestor banner that's still visible so the cursor
        lands on a row the user can actually see.
        """
        if not self._changespec_grouping_active():
            return
        if not self.changespecs:
            self._current_changespec_group_key = None
            return
        registry = self._changespec_group_fold_registry
        entries = build_changespec_tree(
            self.changespecs,
            mode=self._changespec_grouping_mode,
            fold_registry=registry,
        )
        # If the focused CL row is in the visible tree, focus stays on it.
        for entry in entries:
            if entry.kind == "changespec" and entry.changespec_idx == self.current_idx:
                self._current_changespec_group_key = None
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
            if self.current_idx not in g.changespec_indices:
                continue
            if g.level > best_level:
                best_level = g.level
                best_key = g.group_key
        if best_key is not None:
            self._current_changespec_group_key = best_key

    def _reanchor_after_changespec_banner_expansion(
        self, expanded_key: GroupKey
    ) -> None:
        """Move focus off a banner that just stopped being selectable.

        Picks (in order): the first remaining collapsed child banner of
        the expanded group, then the first visible CL of the group, then
        leaves selection alone.
        """
        registry = self._changespec_group_fold_registry
        entries = build_changespec_tree(
            self.changespecs,
            mode=self._changespec_grouping_mode,
            fold_registry=registry,
        )
        expanded_indices: tuple[int, ...] = ()
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.group_key == expanded_key:
                    expanded_indices = entry.group.changespec_indices
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
                self._current_changespec_group_key = g.group_key
                return
        for entry in entries:
            if entry.kind == "changespec" and entry.changespec_idx is not None:
                if entry.changespec_idx in expanded_indices:
                    self._current_changespec_group_key = None
                    self.current_idx = entry.changespec_idx
                    return
        self._current_changespec_group_key = None

    def _expand_changespec_group_fold(self) -> bool:
        """Expand the focused banner's group (``l`` action).

        Returns ``True`` when the registry actually changed so callers
        only refresh the display when something moved.
        """
        if not self._changespec_grouping_active():
            return False
        registry = self._changespec_group_fold_registry
        if self._current_changespec_group_key is not None:
            key: GroupKey = tuple(self._current_changespec_group_key)
            if registry.expand(key):
                self._reanchor_after_changespec_banner_expansion(key)
                return True
            return False
        # Agent focus, no banner — there's nothing collapsed to expand
        # at this level (the focused CL is in an already-expanded group).
        return False

    def _collapse_changespec_group_fold(self) -> bool:
        """Collapse the focused banner or the focused CL's enclosing group.

        ``h`` rules:

        * Banner focus on an L1 sibling-root that's already collapsed →
          escalate to the parent project/date/status banner.
        * Banner focus on any other already-collapsed banner → no-op.
        * Banner focus on an expanded banner → collapse it.
        * Agent focus → collapse the deepest enclosing group (L1 if
          present, else L0) and snap focus to its now-visible banner.
        """
        if not self._changespec_grouping_active():
            return False
        registry = self._changespec_group_fold_registry
        if self._current_changespec_group_key is not None:
            cur_key: GroupKey = tuple(self._current_changespec_group_key)
            if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                parent_key: GroupKey = cur_key[:-1]
                if registry.collapse(parent_key):
                    self._current_changespec_group_key = parent_key
                    return True
                return False
            if registry.collapse(cur_key):
                return True
            return False

        deep_key, l0_key = self._focused_changespec_group_keys()
        target = deep_key or l0_key
        if target is None:
            return False
        if registry.collapse(target):
            self._current_changespec_group_key = target
            self._snap_changespec_focus_after_fold_change()
            return True
        return False

    def _expand_all_changespec_group_folds(self) -> bool:
        """``L`` action: peel one fold layer at the visible-tree level.

        Snapshots the currently-visible entries, then expands every
        collapsed banner in that snapshot.  Rows that become visible *as
        a result of* this press are not stepped — repeated presses peel
        one layer at a time.
        """
        if not self._changespec_grouping_active():
            return False
        registry = self._changespec_group_fold_registry
        entries = build_changespec_tree(
            self.changespecs,
            mode=self._changespec_grouping_mode,
            fold_registry=registry,
        )
        changed = False
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    if registry.expand(entry.group.group_key):
                        changed = True
        if changed:
            self._current_changespec_group_key = None
        return changed

    def _collapse_all_changespec_group_folds(self) -> bool:
        """``H`` action: collapse every currently-expanded banner.

        Snapshots the visible tree and collapses every banner row in
        that snapshot.  Banners hidden behind an already-collapsed
        ancestor are skipped (snapshot-at-start rule); the next ``H``
        press picks them up.
        """
        if not self._changespec_grouping_active():
            return False
        registry = self._changespec_group_fold_registry
        entries = build_changespec_tree(
            self.changespecs,
            mode=self._changespec_grouping_mode,
            fold_registry=registry,
        )
        changed = False
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if not entry.group.is_collapsed:
                if registry.collapse(entry.group.group_key):
                    changed = True
        if changed:
            self._snap_changespec_focus_after_fold_change()
        return changed

    def _changespec_jump_targets(
        self,
    ) -> list[tuple[Literal["changespec", "banner"], object]]:
        """Return jump targets for the CLs tab in render order.

        Mirrors the ``j``/``k`` stops list but is named separately so
        the call site can stay close to other jump-mode helpers.
        Collapsed banners contribute ``("banner", group_key)`` entries;
        expanded banners are non-selectable and excluded.
        """
        return list(self._changespec_navigation_stops())

    def _changespec_banner_focus_still_valid(self) -> bool:
        """Return ``True`` when the active banner key still maps to a banner.

        Used after a CL list reload: if the user was focused on a banner
        whose group was filtered out (e.g. query change dropped its
        last member), drop the stale focus so the cursor falls back to
        a real CL row.  Tolerant of partially-initialized fixtures: a
        harness that never assigned ``_current_changespec_group_key``
        is treated as "no banner focused" (valid).
        """
        key = getattr(self, "_current_changespec_group_key", None)
        if key is None:
            return True
        if not self._changespec_grouping_active():
            return False
        keys = enumerate_changespec_group_keys(
            self.changespecs, mode=self._changespec_grouping_mode
        )
        return tuple(key) in {tuple(k) for k in keys}
