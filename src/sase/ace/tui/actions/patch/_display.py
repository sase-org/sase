"""Patch display refresh logic for the ace TUI app."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ...models.fold_state import FoldLevel
    from ...util.debounce import DetailPanelDebouncer

from ....patch import Patch
from ...models.patch_graph_index import (
    PatchGraphIndex,
    build_patch_graph_index,
)
from ...models.patch_groups import PatchGroupingMode
from ...tab_order import TabName
from ...util.trace import tui_trace
from ._onboarding import PatchOnboardingMixin

log = logging.getLogger(__name__)

# Human-readable badge text per Patch grouping mode.
_PATCH_GROUPING_BADGE_LABELS: dict[PatchGroupingMode, str] = {
    PatchGroupingMode.BY_PROJECT: "by project",
    PatchGroupingMode.BY_DATE: "by date",
    PatchGroupingMode.BY_STATUS: "by status",
}


class PatchDisplayMixin(PatchOnboardingMixin):
    """Mixin providing display refresh, tab-count, and info-panel updates."""

    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    parsed_query: QueryExpr
    hooks_collapsed: FoldLevel
    stitches_collapsed: FoldLevel
    mentors_collapsed: FoldLevel
    timestamps_collapsed: FoldLevel
    deltas_collapsed: FoldLevel
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _hint_mappings: dict[int, str]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    _all_patches: list[Patch]
    _ancestor_keys: dict[str, str]
    _children_keys: dict[str, str]
    _sibling_keys: dict[str, str]
    _hidden_reverted_count: int
    _hidden_submitted_count: int
    _patch_detail_debouncer: DetailPanelDebouncer
    _w_patch_list: object
    _w_patch_detail: object
    _w_ancestors_children: object
    _w_patch_info_panel: object
    _w_footer: object
    _w_search_query_panel: object
    _patch_graph_index: PatchGraphIndex | None
    _patch_graph_index_for_id: int | None
    _patches_first_load_done: bool

    def _patch_detail_surface_active(self) -> bool:
        """Return whether this refresh owns the shared Patch footer."""
        if self.current_tab in {
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            return True
        return (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_subtab", "prs") == "prs"
        )

    def _get_patch_graph_index(self) -> PatchGraphIndex:
        """Return the graph index for ``_all_patches``, building if stale.

        Cached by the list's ``id()`` so 100 j/k selections reuse one
        index instead of rebuilding name / children / status maps 100 times.
        ``_apply_patches`` reassigns ``_all_patches`` on reload, which
        bumps the id and forces a rebuild.
        """
        all_specs = self._all_patches
        list_id = id(all_specs)
        cached = getattr(self, "_patch_graph_index", None)
        cached_id = getattr(self, "_patch_graph_index_for_id", None)
        if cached is not None and cached_id == list_id:
            return cached
        index = build_patch_graph_index(all_specs)
        self._patch_graph_index = index
        self._patch_graph_index_for_id = list_id
        return index

    def _refresh_patches_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the artifacts tab.

        Updates the list cursor and info-panel position immediately;
        debounces the expensive detail/ancestors/footer paint via the
        shared :class:`~..util.debounce.DetailPanelDebouncer` so a long
        press produces exactly one final detail paint when the user
        quiesces. Pure j/k MUST NOT call ``PatchList.update_list``;
        the deferred refresh schedules :meth:`_refresh_patch_detail_only`,
        which updates only detail/ancestors/footer/info-panel.
        """
        with tui_trace("patch.refresh_debounced", patches=len(self.patches)):
            list_widget = self._get_patch_list_widget()
            if list_widget is None:
                log.debug("patches display refresh skipped: widget tree unavailable")
                self._patch_detail_debouncer.cancel()
                return

            if self.patches:
                list_widget.update_highlight(self.current_idx)
            self._update_info_panel()
            self._patch_detail_debouncer.schedule(self._refresh_patch_detail_only)

    def _try_patch_patch_row(self, idx: int) -> bool:
        """Patch a single Patch row in place when shape didn't change.

        Returns ``True`` when the patch landed, ``False`` when the caller
        must fall back to :meth:`_refresh_display`. Callers that flip
        only mark/selection state for one visible row use this to avoid
        the full ``PatchList.update_list`` rebuild.
        """
        if not (0 <= idx < len(self.patches)):
            return False
        list_widget = self._get_patch_list_widget()
        if list_widget is None:
            return False
        hint = (
            self._entry_jump_index_to_hint.get(idx)
            if self._entry_jump_mode_active
            else None
        )
        patch_row = getattr(
            list_widget,
            "patch_patch_row",
            getattr(
                list_widget,
                "patch_changespec_row",  # legacy compatibility alias
                None,
            ),
        )
        if not callable(patch_row):
            return False
        return patch_row(  # type: ignore[no-any-return]
            idx,
            self.patches[idx],
            selected=(idx == self.current_idx),
            marked=(idx in self.marked_indices),
            hint=hint,
        )

    def _refresh_patch_detail_only(self) -> None:
        """Refresh detail / ancestors / footer / info-panel only.

        Used for the debounced j/k navigation path so a selection change
        never rebuilds the option list. List-shape mutations (query,
        filter, fold, hint, mark, reload, visibility) still go through
        :meth:`_refresh_display`.
        """
        with tui_trace("patch.refresh_detail_only", patches=len(self.patches)):
            self._refresh_patch_detail_only_impl()

    def _refresh_patch_detail_only_impl(self) -> None:
        from ....query import query_explicitly_targets_terminal

        if self._sync_patches_onboarding():
            footer_widget = self._get_footer_widget()
            if footer_widget is not None:
                self._apply_empty_footer_update(footer_widget)
            self._update_info_panel()
            return

        detail_widget = self._get_patch_detail_widget()
        ancestors_panel = self._get_ancestors_children_widget()
        footer_widget = self._get_footer_widget()
        if detail_widget is None or ancestors_panel is None or footer_widget is None:
            log.debug("patches detail-only refresh skipped: widget tree unavailable")
            return

        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                self.parsed_query, self._all_patches
            )
        )

        if self.patches and 0 <= self.current_idx < len(self.patches):
            patch = self.patches[self.current_idx]
            self._apply_detail_panel_update(
                detail_widget,
                ancestors_panel,
                footer_widget,
                patch,
                effective_hide_reverted,
            )
        else:
            detail_widget.show_empty(self.canonical_query_string)  # type: ignore[attr-defined]
            self._apply_empty_footer_update(footer_widget)
            ancestors_panel.clear()
            self._ancestor_keys = {}
            self._children_keys = {}
            self._sibling_keys = {}

        self._update_info_panel()

    def _apply_detail_panel_update(
        self,
        detail_widget: Any,
        ancestors_panel: Any,
        footer_widget: Any,
        patch: Patch,
        effective_hide_reverted: bool,
    ) -> None:
        """Drive the four detail-region widgets for a selected Patch."""
        if self._hint_mode_active:
            hint_mappings, hook_hint_to_idx, hint_to_entry_id, _ = (
                detail_widget.update_display_with_hints(  # type: ignore[attr-defined]
                    patch,
                    self.canonical_query_string,  # type: ignore[attr-defined]
                    hints_for=self._hint_mode_hints_for,
                    hooks_collapsed=self.hooks_collapsed,
                    stitches_collapsed=self.stitches_collapsed,
                    mentors_collapsed=self.mentors_collapsed,
                    timestamps_collapsed=self.timestamps_collapsed,
                    deltas_collapsed=self.deltas_collapsed,
                )
            )
            self._hint_mappings = hint_mappings
            self._hook_hint_to_idx = hook_hint_to_idx
            self._hint_to_entry_id = hint_to_entry_id
        else:
            detail_widget.update_display(  # type: ignore[attr-defined]
                patch,
                self.canonical_query_string,  # type: ignore[attr-defined]
                hooks_collapsed=self.hooks_collapsed,
                stitches_collapsed=self.stitches_collapsed,
                mentors_collapsed=self.mentors_collapsed,
                timestamps_collapsed=self.timestamps_collapsed,
                deltas_collapsed=self.deltas_collapsed,
            )
        graph_index = self._get_patch_graph_index()
        self._ancestor_keys, self._children_keys, self._sibling_keys = (
            ancestors_panel.update_relationships_from_index(  # type: ignore[attr-defined]
                patch,
                graph_index,
                hide_reverted=effective_hide_reverted,
            )
        )
        # The keybinding footer is shared across tabs; the active tab's
        # display path is the sole writer. When the PR refresh fires
        # off-tab (e.g. inotify-driven reload while the user is on
        # Agents), the writes here would clobber the active tab's
        # bindings and flicker.
        if not self._patch_detail_surface_active():
            return
        if getattr(self, "_fold_mode_active", False):
            from ...models.fold_scale import CLAN_FOLD_SCALE

            footer_widget.update_fold_bindings(  # type: ignore[attr-defined]
                current_tab="artifacts",
                fold_scale=CLAN_FOLD_SCALE,
            )
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings()  # type: ignore[attr-defined]
        elif getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()  # type: ignore[attr-defined]
        elif getattr(self, "_copy_mode_active", False):
            footer_widget.update_copy_bindings(  # type: ignore[attr-defined]
                self.current_tab,
                artifacts_pane_key=getattr(self, "current_artifacts_pane_key", None),
            )
        elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
            footer_widget.update_custom_mode_bindings(cm)  # type: ignore[attr-defined]
        else:
            footer_widget.update_bindings(  # type: ignore[attr-defined]
                patch, mark_count=len(self.marked_indices)
            )

    def _apply_empty_footer_update(self, footer_widget: Any) -> None:
        """Footer update for the empty-list branch (no selected Patch)."""
        # See ``_apply_detail_panel_update`` — never write the shared
        # footer when this refresh fires off-tab.
        if not self._patch_detail_surface_active():
            return
        if getattr(self, "_fold_mode_active", False):
            return
        if getattr(self, "_leader_mode_active", False):
            return
        if getattr(self, "_bang_mode_active", False):
            return
        if getattr(self, "_copy_mode_active", False):
            return
        if getattr(self, "_custom_mode_active", None) is not None:
            return
        from ....query import get_sole_project_filter

        sole_project = get_sole_project_filter(self.parsed_query)
        footer_widget.show_empty(project_name=sole_project)  # type: ignore[attr-defined]

    def _get_patch_list_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import PatchList

        cached = getattr(self, "_w_patch_list", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#list-panel", PatchList)  # type: ignore[attr-defined]
        except NoMatches:
            return None

    def _get_patch_detail_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import PatchDetail

        cached = getattr(self, "_w_patch_detail", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#detail-panel", PatchDetail)  # type: ignore[attr-defined]
        except NoMatches:
            return None

    def _get_ancestors_children_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import AncestorsChildrenPanel

        cached = getattr(self, "_w_ancestors_children", None)
        if cached is not None:
            return cached
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#ancestors-children-panel", AncestorsChildrenPanel
            )
        except NoMatches:
            return None

    def _get_footer_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import KeybindingFooter

        cached = getattr(self, "_w_footer", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            return None

    def _get_search_query_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import SearchQueryPanel

        cached = getattr(self, "_w_search_query_panel", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#search-query-panel", SearchQueryPanel)  # type: ignore[attr-defined]
        except NoMatches:
            return None

    def _refresh_display(self) -> None:
        """Refresh the display with current state."""
        with tui_trace("patch.refresh_display", patches=len(self.patches)):
            self._refresh_display_impl()

    def _refresh_display_impl(self) -> None:
        # Full refresh supersedes any pending debounced detail update.
        self._patch_detail_debouncer.cancel()

        search_panel = self._get_search_query_widget()
        if search_panel is not None:
            search_panel.update_query(self.canonical_query_string)  # type: ignore[attr-defined]

        if self._sync_patches_onboarding():
            footer_widget = self._get_footer_widget()
            if footer_widget is not None:
                self._apply_empty_footer_update(footer_widget)
            self._update_info_panel()
            return

        list_widget = self._get_patch_list_widget()
        detail_widget = self._get_patch_detail_widget()
        footer_widget = self._get_footer_widget()
        ancestors_panel = self._get_ancestors_children_widget()
        if (
            list_widget is None
            or detail_widget is None
            or search_panel is None
            or footer_widget is None
            or ancestors_panel is None
        ):
            log.debug("patches full refresh skipped: widget tree unavailable")
            return

        from ....query import query_explicitly_targets_terminal

        from ...models.patch_groups import enumerate_patch_group_keys

        grouping_mode: PatchGroupingMode = getattr(
            self, "_patch_grouping_mode", PatchGroupingMode.BY_PROJECT
        )
        fold_registry = getattr(self, "_patch_group_fold_registry", None)
        if fold_registry is not None:
            # Drop collapse intent for groups whose last member dropped
            # out of the filtered set — otherwise a key from a previous
            # query would silently re-collapse if the same group reappeared.
            fold_registry.clear_unknown(
                enumerate_patch_group_keys(self.patches, mode=grouping_mode)
            )
        current_group_key = getattr(self, "_current_patch_group_key", None)
        banner_jump_hints = (
            dict(getattr(self, "_entry_jump_patch_banner_to_hint", {}) or {})
            if self._entry_jump_mode_active
            else None
        )
        list_widget.update_list(  # type: ignore[attr-defined]
            self.patches,
            self.current_idx,
            self.marked_indices,
            hide_reverted=self.hide_reverted,
            hide_submitted=self.hide_submitted,
            jump_hints=(
                self._entry_jump_index_to_hint if self._entry_jump_mode_active else None
            ),
            grouping_mode=grouping_mode,
            fold_registry=fold_registry,
            current_group_key=current_group_key,
            banner_jump_hints=banner_jump_hints,
        )

        # Calculate effective hide_reverted (disabled if query targets reverted)
        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                self.parsed_query, self._all_patches
            )
        )

        if self.patches and 0 <= self.current_idx < len(self.patches):
            patch = self.patches[self.current_idx]
            self._apply_detail_panel_update(
                detail_widget,
                ancestors_panel,
                footer_widget,
                patch,
                effective_hide_reverted,
            )
        else:
            detail_widget.show_empty(self.canonical_query_string)  # type: ignore[attr-defined]
            self._apply_empty_footer_update(footer_widget)
            ancestors_panel.clear()
            self._ancestor_keys = {}
            self._children_keys = {}
            self._sibling_keys = {}

        self._update_info_panel()

    def _update_info_panel(self) -> None:
        """Update the info panel with current position and countdown."""
        from textual.css.query import NoMatches

        from ...widgets import PatchInfoPanel

        info_panel = getattr(self, "_w_patch_info_panel", None)
        if info_panel is None:
            try:
                info_panel = self.query_one("#info-panel", PatchInfoPanel)  # type: ignore[attr-defined]
            except NoMatches:
                return
        # Position is 1-based for display (current_idx is 0-based)
        position = self.current_idx + 1 if self.patches else 0
        info_panel.update_position(
            position, len(self.patches), len(self.marked_indices)
        )
        info_panel.update_hidden_counts(
            self._hidden_reverted_count, self._hidden_submitted_count
        )
        cs_mode: PatchGroupingMode = getattr(
            self, "_patch_grouping_mode", PatchGroupingMode.BY_PROJECT
        )
        info_panel.update_grouping_mode(_PATCH_GROUPING_BADGE_LABELS[cs_mode])
        info_panel.update_countdown(self._countdown_remaining, self.refresh_interval)  # type: ignore[attr-defined]
