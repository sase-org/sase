"""ChangeSpec display refresh logic for the ace TUI app."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ...models.fold_state import FoldLevel
    from ...util.debounce import DetailPanelDebouncer

from ....changespec import ChangeSpec
from ...util.trace import tui_trace

log = logging.getLogger(__name__)

TabName = Literal["changespecs", "agents", "axe"]


class ChangeSpecDisplayMixin:
    """Mixin providing display refresh, tab-count, and info-panel updates."""

    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    parsed_query: QueryExpr
    hooks_collapsed: FoldLevel
    commits_collapsed: FoldLevel
    mentors_collapsed: FoldLevel
    timestamps_collapsed: FoldLevel
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
    _all_changespecs: list[ChangeSpec]
    _ancestor_keys: dict[str, str]
    _children_keys: dict[str, str]
    _sibling_keys: dict[str, str]
    _hidden_reverted_count: int
    _query_reverted_count: int
    _hidden_submitted_count: int
    _query_submitted_count: int
    _changespec_detail_debouncer: DetailPanelDebouncer
    _w_changespec_list: object
    _w_changespec_detail: object
    _w_ancestors_children: object
    _w_changespec_info_panel: object
    _w_footer: object
    _w_search_query_panel: object

    def _update_cls_tab_count(self) -> None:
        """Update the CLs tab bar label with current ChangeSpec counts."""
        from ...widgets import TabBar

        show_reverted = not self.hide_reverted
        show_submitted = not self.hide_submitted

        # Main count: total displayed minus any visible special statuses
        main = len(self.changespecs)
        if show_reverted:
            main -= self._query_reverted_count
        if show_submitted:
            main -= self._query_submitted_count

        try:
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.update_cls_count(
                main,
                self._query_reverted_count,
                show_hidden=show_reverted,
                submitted_count=self._query_submitted_count,
                show_submitted=show_submitted,
            )
        except Exception:
            pass

    def _refresh_changespecs_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the changespecs tab.

        Updates the list cursor and info-panel position immediately;
        debounces the expensive detail/ancestors/footer paint via the
        shared :class:`~..util.debounce.DetailPanelDebouncer` so a long
        press produces exactly one final detail paint when the user
        quiesces. Pure j/k MUST NOT call ``ChangeSpecList.update_list``;
        the deferred refresh schedules :meth:`_refresh_changespec_detail_only`,
        which updates only detail/ancestors/footer/info-panel.
        """
        with tui_trace(
            "changespec.refresh_debounced", changespecs=len(self.changespecs)
        ):
            list_widget = self._get_changespec_list_widget()
            if list_widget is None:
                log.debug(
                    "changespecs display refresh skipped: widget tree unavailable"
                )
                self._changespec_detail_debouncer.cancel()
                return

            if self.changespecs:
                list_widget.update_highlight(self.current_idx)
            self._update_info_panel()
            self._changespec_detail_debouncer.schedule(
                self._refresh_changespec_detail_only
            )

    def _try_patch_changespec_row(self, idx: int) -> bool:
        """Patch a single ChangeSpec row in place when shape didn't change.

        Returns ``True`` when the patch landed, ``False`` when the caller
        must fall back to :meth:`_refresh_display`. Callers that flip
        only mark/selection state for one visible row use this to avoid
        the full ``ChangeSpecList.update_list`` rebuild.
        """
        if not (0 <= idx < len(self.changespecs)):
            return False
        list_widget = self._get_changespec_list_widget()
        if list_widget is None:
            return False
        hint = (
            self._entry_jump_index_to_hint.get(idx)
            if self._entry_jump_mode_active
            else None
        )
        return list_widget.patch_changespec_row(  # type: ignore[no-any-return]
            idx,
            self.changespecs[idx],
            selected=(idx == self.current_idx),
            marked=(idx in self.marked_indices),
            hint=hint,
        )

    def _refresh_changespec_detail_only(self) -> None:
        """Refresh detail / ancestors / footer / info-panel only.

        Used for the debounced j/k navigation path so a selection change
        never rebuilds the option list. List-shape mutations (query,
        filter, fold, hint, mark, reload, visibility) still go through
        :meth:`_refresh_display`.
        """
        with tui_trace(
            "changespec.refresh_detail_only", changespecs=len(self.changespecs)
        ):
            self._refresh_changespec_detail_only_impl()

    def _refresh_changespec_detail_only_impl(self) -> None:
        from ....query import query_explicitly_targets_terminal

        detail_widget = self._get_changespec_detail_widget()
        ancestors_panel = self._get_ancestors_children_widget()
        footer_widget = self._get_footer_widget()
        if detail_widget is None or ancestors_panel is None or footer_widget is None:
            log.debug(
                "changespecs detail-only refresh skipped: widget tree unavailable"
            )
            return

        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                self.parsed_query, self._all_changespecs
            )
        )

        if self.changespecs and 0 <= self.current_idx < len(self.changespecs):
            changespec = self.changespecs[self.current_idx]
            self._apply_detail_panel_update(
                detail_widget,
                ancestors_panel,
                footer_widget,
                changespec,
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
        changespec: ChangeSpec,
        effective_hide_reverted: bool,
    ) -> None:
        """Drive the four detail-region widgets for a selected ChangeSpec."""
        if self._hint_mode_active:
            hint_mappings, hook_hint_to_idx, hint_to_entry_id, _ = (
                detail_widget.update_display_with_hints(  # type: ignore[attr-defined]
                    changespec,
                    self.canonical_query_string,  # type: ignore[attr-defined]
                    hints_for=self._hint_mode_hints_for,
                    hooks_collapsed=self.hooks_collapsed,
                    commits_collapsed=self.commits_collapsed,
                    mentors_collapsed=self.mentors_collapsed,
                    timestamps_collapsed=self.timestamps_collapsed,
                )
            )
            self._hint_mappings = hint_mappings
            self._hook_hint_to_idx = hook_hint_to_idx
            self._hint_to_entry_id = hint_to_entry_id
        else:
            detail_widget.update_display(  # type: ignore[attr-defined]
                changespec,
                self.canonical_query_string,  # type: ignore[attr-defined]
                hooks_collapsed=self.hooks_collapsed,
                commits_collapsed=self.commits_collapsed,
                mentors_collapsed=self.mentors_collapsed,
                timestamps_collapsed=self.timestamps_collapsed,
            )
        self._ancestor_keys, self._children_keys, self._sibling_keys = (
            ancestors_panel.update_relationships(  # type: ignore[attr-defined]
                changespec,
                self._all_changespecs,
                hide_reverted=effective_hide_reverted,
            )
        )
        if getattr(self, "_fold_mode_active", False):
            footer_widget.update_fold_bindings()  # type: ignore[attr-defined]
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings()  # type: ignore[attr-defined]
        elif getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()  # type: ignore[attr-defined]
        elif getattr(self, "_copy_mode_active", False):
            footer_widget.update_copy_bindings(self.current_tab)  # type: ignore[attr-defined]
        elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
            footer_widget.update_custom_mode_bindings(cm)  # type: ignore[attr-defined]
        else:
            footer_widget.update_bindings(  # type: ignore[attr-defined]
                changespec, mark_count=len(self.marked_indices)
            )

    def _apply_empty_footer_update(self, footer_widget: Any) -> None:
        """Footer update for the empty-list branch (no selected ChangeSpec)."""
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

    def _get_changespec_list_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import ChangeSpecList

        cached = getattr(self, "_w_changespec_list", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#list-panel", ChangeSpecList)  # type: ignore[attr-defined]
        except NoMatches:
            return None

    def _get_changespec_detail_widget(self) -> Any:
        from textual.css.query import NoMatches

        from ...widgets import ChangeSpecDetail

        cached = getattr(self, "_w_changespec_detail", None)
        if cached is not None:
            return cached
        try:
            return self.query_one("#detail-panel", ChangeSpecDetail)  # type: ignore[attr-defined]
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
        with tui_trace("changespec.refresh_display", changespecs=len(self.changespecs)):
            self._refresh_display_impl()

    def _refresh_display_impl(self) -> None:
        # Full refresh supersedes any pending debounced detail update.
        self._changespec_detail_debouncer.cancel()

        list_widget = self._get_changespec_list_widget()
        detail_widget = self._get_changespec_detail_widget()
        search_panel = self._get_search_query_widget()
        footer_widget = self._get_footer_widget()
        ancestors_panel = self._get_ancestors_children_widget()
        if (
            list_widget is None
            or detail_widget is None
            or search_panel is None
            or footer_widget is None
            or ancestors_panel is None
        ):
            log.debug("changespecs full refresh skipped: widget tree unavailable")
            return

        from ....query import query_explicitly_targets_terminal

        list_widget.update_list(  # type: ignore[attr-defined]
            self.changespecs,
            self.current_idx,
            self.marked_indices,
            hide_reverted=self.hide_reverted,
            hide_submitted=self.hide_submitted,
            jump_hints=(
                self._entry_jump_index_to_hint if self._entry_jump_mode_active else None
            ),
        )
        search_panel.update_query(self.canonical_query_string)  # type: ignore[attr-defined]

        # Calculate effective hide_reverted (disabled if query targets reverted)
        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(
                self.parsed_query, self._all_changespecs
            )
        )

        if self.changespecs and 0 <= self.current_idx < len(self.changespecs):
            changespec = self.changespecs[self.current_idx]
            self._apply_detail_panel_update(
                detail_widget,
                ancestors_panel,
                footer_widget,
                changespec,
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

        from ...widgets import ChangeSpecInfoPanel

        info_panel = getattr(self, "_w_changespec_info_panel", None)
        if info_panel is None:
            try:
                info_panel = self.query_one("#info-panel", ChangeSpecInfoPanel)  # type: ignore[attr-defined]
            except NoMatches:
                return
        # Position is 1-based for display (current_idx is 0-based)
        position = self.current_idx + 1 if self.changespecs else 0
        info_panel.update_position(
            position, len(self.changespecs), len(self.marked_indices)
        )
        info_panel.update_hidden_counts(
            self._hidden_reverted_count, self._hidden_submitted_count
        )
        info_panel.update_countdown(self._countdown_remaining, self.refresh_interval)  # type: ignore[attr-defined]
