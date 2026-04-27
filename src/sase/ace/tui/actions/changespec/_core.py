"""ChangeSpec management mixin for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from ._display import ChangeSpecDisplayMixin
from ._loading import ChangeSpecLoadingMixin
from ._query import ChangeSpecQueryMixin

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ...models.fold_state import FoldLevel
    from ...util.debounce import DetailPanelDebouncer

from ....changespec import ChangeSpec

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class ChangeSpecMixin(
    ChangeSpecLoadingMixin,
    ChangeSpecQueryMixin,
    ChangeSpecDisplayMixin,
):
    """Mixin providing ChangeSpec loading, filtering, and display methods."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    query_string: str
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
    _leader_mode_active: bool
    _hint_mappings: dict[int, str]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    _query_history: QueryHistoryStacks
    _query_selections: dict[str, str]
    _all_changespecs: list[ChangeSpec]
    _ancestor_keys: dict[str, str]
    _children_keys: dict[str, str]
    _sibling_keys: dict[str, str]
    _hidden_reverted_count: int
    _query_reverted_count: int
    _hidden_submitted_count: int
    _query_submitted_count: int
    _axe_cmds_hidden: bool
    _changespecs_loading: bool
    _changespecs_refresh_pending: bool

    # Debouncer for j/k navigation detail panel updates (changespecs tab).
    _changespec_detail_debouncer: DetailPanelDebouncer

    def action_edit_spec(self) -> None:
        """Edit the current ChangeSpec in $EDITOR."""
        if not self.changespecs:
            return
        changespec = self.changespecs[self.current_idx]
        self._open_spec_in_editor(changespec)

    def _open_spec_in_editor(self, changespec: ChangeSpec) -> None:
        """Open ChangeSpec in editor with nvim enhancements."""
        import subprocess

        from ....changespec.locking import acquire_edit_lock, release_edit_lock

        editor = os.environ.get("EDITOR") or "nvim"
        file_path = os.path.expanduser(changespec.file_path)
        args = [editor]
        if "/nvim" in editor:
            args.extend(
                [
                    "-c",
                    f"/NAME: \\zs{changespec.name}$",
                    "-c",
                    "normal zz",
                    "-c",
                    "nohlsearch",
                ]
            )
        args.append(file_path)
        acquire_edit_lock(file_path)
        try:
            with self.suspend():  # type: ignore[attr-defined]
                subprocess.run(args, check=False)
        finally:
            release_edit_lock(file_path)

    def _save_selection_for_current_query(self) -> None:
        """Save the current ChangeSpec selection keyed by current query."""
        from ....query_selection import save_query_selections

        if self.changespecs:
            idx = min(self.current_idx, len(self.changespecs) - 1)
            name = self.changespecs[idx].name
            canonical = self.canonical_query_string  # type: ignore[attr-defined]
            # Pop and re-insert to mark as recently used
            self._query_selections.pop(canonical, None)
            self._query_selections[canonical] = name
            save_query_selections(self._query_selections)

    def _restore_selection_for_current_query(self) -> None:
        """Restore the saved ChangeSpec selection for the current query."""
        canonical = self.canonical_query_string  # type: ignore[attr-defined]
        saved_name = self._query_selections.get(canonical)
        if saved_name is None:
            return
        for idx, cs in enumerate(self.changespecs):
            if cs.name == saved_name:
                self.current_idx = idx
                return

    def action_toggle_hide_reverted(self) -> None:
        """Toggle visibility of reverted CLs, non-run agents, or axe commands."""
        if self.current_tab == "agents":
            self._toggle_hide_non_run_agents()  # type: ignore[attr-defined]
            return
        if self.current_tab == "axe":
            self._axe_cmds_hidden = not self._axe_cmds_hidden  # type: ignore[attr-defined]
            # If hiding and current selection is a bgcmd, navigate to axe parent
            from ...widgets.bgcmd_list import BgCmdItem

            axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
            if (
                self._axe_cmds_hidden
                and axe_items
                and 0 <= self.current_idx < len(axe_items)
                and isinstance(axe_items[self.current_idx], BgCmdItem)
            ):
                self.current_idx = 0
            self._build_axe_items()  # type: ignore[attr-defined]
            self._update_axe_tab_count()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]
            return
        if self.current_tab != "changespecs":
            return
        self.hide_reverted = not self.hide_reverted
        self._reload_and_reposition()

    def action_toggle_hide_submitted(self) -> None:
        """Toggle visibility of submitted CLs."""
        if self.current_tab != "changespecs":
            return
        self.hide_submitted = not self.hide_submitted
        self._reload_and_reposition()
