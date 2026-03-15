"""ChangeSpec management mixin for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ...query.types import QueryExpr
    from ...query_history import QueryHistoryStacks
    from ..models.fold_state import FoldLevel

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class ChangeSpecMixin:
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
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _leader_mode_active: bool
    _hint_mappings: dict[int, str]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
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

    def _load_changespecs(self) -> None:
        """Load and filter changespecs from disk."""
        from ...changespec import find_all_changespecs

        all_changespecs = find_all_changespecs()
        self._all_changespecs = all_changespecs  # Cache for ancestry lookup
        self.changespecs = self._filter_changespecs(all_changespecs)

        # Clear marks on reload (indices may shift)
        self.marked_indices = set()  # type: ignore[assignment]

        # Ensure current_idx is within bounds
        if self.changespecs:
            if self.current_idx >= len(self.changespecs):
                self.current_idx = len(self.changespecs) - 1
        else:
            self.current_idx = 0

        self._update_cls_tab_count()
        self._refresh_display()

    def _filter_changespecs(self, changespecs: list[ChangeSpec]) -> list[ChangeSpec]:
        """Filter changespecs using the parsed query and hide settings."""
        from ...changespec import get_base_status
        from ...query import (
            evaluate_query,
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )

        # First apply the query filter
        result = [
            cs
            for cs in changespecs
            if evaluate_query(self.parsed_query, cs, changespecs)
        ]

        # Count reverted/archived and submitted in query results (for tab bar)
        self._query_reverted_count = 0
        self._query_submitted_count = 0
        for cs in result:
            base_status = get_base_status(cs.status)
            if base_status in ("Reverted", "Archived"):
                self._query_reverted_count += 1
            elif base_status == "Submitted":
                self._query_submitted_count += 1

        # Determine effective hide settings (disabled if query targets them)
        effective_hide_reverted = (
            self.hide_reverted
            and not query_explicitly_targets_terminal(self.parsed_query, changespecs)
        )
        effective_hide_submitted = (
            self.hide_submitted
            and not query_explicitly_targets_submitted(self.parsed_query, changespecs)
        )

        # Filter out hidden statuses
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        if effective_hide_reverted or effective_hide_submitted:
            filtered: list[ChangeSpec] = []
            for cs in result:
                base_status = get_base_status(cs.status)
                if effective_hide_reverted and base_status in ("Reverted", "Archived"):
                    self._hidden_reverted_count += 1
                elif effective_hide_submitted and base_status == "Submitted":
                    self._hidden_submitted_count += 1
                else:
                    filtered.append(cs)
            result = filtered

        return result

    def _reload_and_reposition(self, current_name: str | None = None) -> None:
        """Reload changespecs and try to stay on the same one."""
        from ...changespec import find_all_changespecs

        if current_name is None and self.changespecs:
            idx = min(self.current_idx, len(self.changespecs) - 1)
            current_name = self.changespecs[idx].name

        all_changespecs = find_all_changespecs()
        self._all_changespecs = all_changespecs  # Cache for ancestry lookup
        new_changespecs = self._filter_changespecs(all_changespecs)

        # Try to find the same changespec by name
        new_idx = 0
        if current_name:
            for idx, cs in enumerate(new_changespecs):
                if cs.name == current_name:
                    new_idx = idx
                    break

        self.changespecs = new_changespecs  # type: ignore[assignment]
        self.current_idx = new_idx
        self._update_cls_tab_count()
        self._refresh_display()

    def _save_current_query(self) -> None:
        """Save the current query as the last used query."""
        from ...saved_queries import save_last_query

        save_last_query(self.canonical_query_string)  # type: ignore[attr-defined]

    def _load_saved_query(self, slot: str) -> None:
        """Load a saved query from a slot.

        Args:
            slot: The slot number ("0"-"9").
        """
        # Switch to CLs tab if not already there
        if self.current_tab != "changespecs":
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = "changespecs"  # type: ignore[assignment]

        from ...query import parse_query, to_canonical_string
        from ...query_history import push_to_prev_stack, save_query_history
        from ...saved_queries import load_saved_queries

        queries = load_saved_queries()
        if slot not in queries:
            self.notify(f"No query saved in slot {slot}", severity="warning")  # type: ignore[attr-defined]
            return

        query = queries[slot]
        try:
            new_parsed = parse_query(query)
            new_canonical = to_canonical_string(new_parsed)

            # Only push to history if query actually changes
            current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
            if new_canonical != current_canonical:
                self._save_selection_for_current_query()
                push_to_prev_stack(current_canonical, self._query_history)
                save_query_history(self._query_history)

            self.parsed_query = new_parsed
            self.query_string = query
            self._load_changespecs()
            self._restore_selection_for_current_query()
            self._save_current_query()
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def _try_startup_fallback(self) -> bool:
        """Try saved queries as fallback when the startup query has no results.

        Checks slots 1-9 then 0. If a saved query produces results, switches
        to it and returns True.  Returns False if no saved query has results.
        """
        from ...query import parse_query, to_canonical_string
        from ...saved_queries import load_saved_queries

        queries = load_saved_queries()
        if not queries:
            return False

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        original_parsed = self.parsed_query
        original_string = self.query_string

        slot_order = [str(i) for i in range(1, 10)] + ["0"]
        for slot in slot_order:
            if slot not in queries:
                continue
            query = queries[slot]
            try:
                parsed = parse_query(query)
                canonical = to_canonical_string(parsed)
                # Skip if identical to the initial query (already tried)
                if canonical == current_canonical:
                    continue
                # Temporarily set the query so _filter_changespecs uses it
                self.parsed_query = parsed
                self.query_string = query
                filtered = self._filter_changespecs(self._all_changespecs)
                if filtered:
                    # Found results – fully load this query
                    self._load_changespecs()
                    self._restore_selection_for_current_query()
                    return True
            except Exception:
                continue

        # No saved query produced results – restore original state
        self.parsed_query = original_parsed
        self.query_string = original_string
        return False

    # --- Saved Query Actions ---

    def action_load_saved_query_1(self) -> None:
        """Load saved query from slot 1."""
        self._load_saved_query("1")

    def action_load_saved_query_2(self) -> None:
        """Load saved query from slot 2."""
        self._load_saved_query("2")

    def action_load_saved_query_3(self) -> None:
        """Load saved query from slot 3."""
        self._load_saved_query("3")

    def action_load_saved_query_4(self) -> None:
        """Load saved query from slot 4."""
        self._load_saved_query("4")

    def action_load_saved_query_5(self) -> None:
        """Load saved query from slot 5."""
        self._load_saved_query("5")

    def action_load_saved_query_6(self) -> None:
        """Load saved query from slot 6."""
        self._load_saved_query("6")

    def action_load_saved_query_7(self) -> None:
        """Load saved query from slot 7."""
        self._load_saved_query("7")

    def action_load_saved_query_8(self) -> None:
        """Load saved query from slot 8."""
        self._load_saved_query("8")

    def action_load_saved_query_9(self) -> None:
        """Load saved query from slot 9."""
        self._load_saved_query("9")

    def action_load_saved_query_0(self) -> None:
        """Load saved query from slot 0."""
        self._load_saved_query("0")

    # --- Query History Navigation Actions ---

    def action_prev_query(self) -> None:
        """Navigate to previous query in history (^ key)."""
        from ...query import parse_query
        from ...query_history import navigate_prev, save_query_history

        if self.current_tab != "changespecs":
            return

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        self._save_selection_for_current_query()
        prev_query = navigate_prev(current_canonical, self._query_history)
        if prev_query is None:
            self.notify("No previous query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = parse_query(prev_query)
            self.query_string = prev_query
            self._load_changespecs()
            self._restore_selection_for_current_query()
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def action_next_query(self) -> None:
        """Navigate to next query in history (_ key)."""
        from ...query import parse_query
        from ...query_history import navigate_next, save_query_history

        if self.current_tab != "changespecs":
            return

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        self._save_selection_for_current_query()
        next_query = navigate_next(current_canonical, self._query_history)
        if next_query is None:
            self.notify("No next query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = parse_query(next_query)
            self.query_string = next_query
            self._load_changespecs()
            self._restore_selection_for_current_query()
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def _update_cls_tab_count(self) -> None:
        """Update the CLs tab bar label with current ChangeSpec counts."""
        from ..widgets import TabBar

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

    def _refresh_display(self) -> None:
        """Refresh the display with current state."""
        from ...query import query_explicitly_targets_terminal
        from ..widgets import (
            AncestorsChildrenPanel,
            ChangeSpecDetail,
            ChangeSpecList,
            KeybindingFooter,
            SearchQueryPanel,
        )

        list_widget = self.query_one("#list-panel", ChangeSpecList)  # type: ignore[attr-defined]
        detail_widget = self.query_one("#detail-panel", ChangeSpecDetail)  # type: ignore[attr-defined]
        search_panel = self.query_one("#search-query-panel", SearchQueryPanel)  # type: ignore[attr-defined]
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        ancestors_panel = self.query_one(  # type: ignore[attr-defined]
            "#ancestors-children-panel", AncestorsChildrenPanel
        )

        list_widget.update_list(
            self.changespecs,
            self.current_idx,
            self.marked_indices,
            hide_reverted=self.hide_reverted,
            hide_submitted=self.hide_submitted,
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
            # Preserve hints if in hint mode
            if self._hint_mode_active:
                # Respect collapsed states: show hints only on visible lines
                hint_mappings, hook_hint_to_idx, hint_to_entry_id, _ = (
                    detail_widget.update_display_with_hints(
                        changespec,
                        self.canonical_query_string,  # type: ignore[attr-defined]
                        hints_for=self._hint_mode_hints_for,
                        hooks_collapsed=self.hooks_collapsed,
                        commits_collapsed=self.commits_collapsed,
                        mentors_collapsed=self.mentors_collapsed,
                    )
                )
                self._hint_mappings = hint_mappings
                self._hook_hint_to_idx = hook_hint_to_idx
                self._hint_to_entry_id = hint_to_entry_id
            else:
                detail_widget.update_display(
                    changespec,
                    self.canonical_query_string,  # type: ignore[attr-defined]
                    hooks_collapsed=self.hooks_collapsed,
                    commits_collapsed=self.commits_collapsed,
                    mentors_collapsed=self.mentors_collapsed,
                )
            # Update ancestors/children/siblings panel with hide_reverted
            self._ancestor_keys, self._children_keys, self._sibling_keys = (
                ancestors_panel.update_relationships(
                    changespec,
                    self._all_changespecs,
                    hide_reverted=effective_hide_reverted,
                )
            )
            # Preserve modal mode footers during auto-refresh
            if getattr(self, "_leader_mode_active", False):
                footer_widget.update_leader_bindings()
            elif getattr(self, "_bang_mode_active", False):
                footer_widget.update_bang_bindings()
            elif getattr(self, "_copy_mode_active", False):
                footer_widget.update_copy_bindings(self.current_tab)
            else:
                footer_widget.update_bindings(
                    changespec, mark_count=len(self.marked_indices)
                )
        else:
            detail_widget.show_empty(self.canonical_query_string)  # type: ignore[attr-defined]
            if getattr(self, "_leader_mode_active", False):
                pass  # preserve leader mode footer
            elif getattr(self, "_bang_mode_active", False):
                pass  # preserve bang mode footer
            elif getattr(self, "_copy_mode_active", False):
                pass  # preserve copy mode footer
            else:
                footer_widget.show_empty()
            ancestors_panel.clear()
            self._ancestor_keys = {}
            self._children_keys = {}
            self._sibling_keys = {}

        self._update_info_panel()

    def _update_info_panel(self) -> None:
        """Update the info panel with current position and countdown."""
        from textual.css.query import NoMatches

        from ..widgets import ChangeSpecInfoPanel

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

    def action_edit_spec(self) -> None:
        """Edit the current ChangeSpec in $EDITOR."""
        if not self.changespecs:
            return
        changespec = self.changespecs[self.current_idx]
        self._open_spec_in_editor(changespec)

    def _open_spec_in_editor(self, changespec: ChangeSpec) -> None:
        """Open ChangeSpec in editor with nvim enhancements."""
        import subprocess

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
        with self.suspend():  # type: ignore[attr-defined]
            subprocess.run(args, check=False)

    def _save_selection_for_current_query(self) -> None:
        """Save the current ChangeSpec selection keyed by current query."""
        from ...query_selection import save_query_selections

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
            from ..widgets.bgcmd_list import BgCmdItem

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
