"""Saved-query slots and query-history navigation for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks

from ....patch import Patch

TabName = Literal["artifacts", "agents", "axe"]


class PatchQueryMixin:
    """Mixin providing saved-query slot loading and history navigation."""

    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    parsed_query: QueryExpr
    query_string: str
    _all_patches: list[Patch]
    _query_history: QueryHistoryStacks
    _query_selections: dict[str, str]
    _saved_queries: dict[str, str]

    def _save_current_query(self) -> None:
        """Save the current query as the last used query."""
        from ....saved_queries import save_last_query

        save_last_query(self.canonical_query_string)  # type: ignore[attr-defined]

    def _load_query_patches(self) -> None:
        """Reload patches through the legacy-compatible app method."""
        legacy_load = self.__dict__.get(  # legacy compatibility alias
            "_load_changespecs"
        )
        if callable(legacy_load):
            legacy_load()
            return
        load = getattr(self, "_load_patches", None)
        if callable(load):
            load()
            return
        self._load_patches()  # type: ignore[attr-defined]

    def _load_saved_query(self, slot: str) -> None:
        """Load a saved query from a slot.

        Args:
            slot: The slot number ("0"-"9").
        """
        # Saved queries are shown on the Artifacts tab's PRs sub-tab, so land
        # there even when called from another tab (e.g. an Agents keymap) or
        # from the Artifacts tab on a non-PR sub-tab (e.g. Commits).
        on_prs_pane = (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_subtab", "prs") == "prs"
        )
        if not on_prs_pane:
            if self.current_tab != "artifacts":
                self._save_current_tab_position()  # type: ignore[attr-defined]
            from ...artifact_tabs import switch_to_artifacts_subtab

            switch_to_artifacts_subtab(self, "prs")

        from ....query import parse_query, to_canonical_string
        from ....query_history import push_to_prev_stack, save_query_history

        queries = self._saved_queries
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
                self._save_selection_for_current_query()  # type: ignore[attr-defined]
                push_to_prev_stack(current_canonical, self._query_history)
                save_query_history(self._query_history)

            self.parsed_query = new_parsed
            self.query_string = query
            self._load_query_patches()
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def action_start_saved_query_mode(self) -> None:
        """Arm direct saved-query slot selection (0 then a digit)."""
        if self.current_tab != "artifacts":
            return
        self._saved_query_mode_active = True  # type: ignore[attr-defined]
        self._update_saved_query_footer()

    def _handle_saved_query_key(self, key: str) -> bool:
        """Handle a key press in saved-query mode. Returns True if handled."""
        # Always exit saved-query mode (one-shot, like bang/checkout mode).
        self._saved_query_mode_active = False  # type: ignore[attr-defined]

        if key == "escape":
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if len(key) == 1 and key.isdigit():
            self._load_saved_query(key)
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Unknown key - just exit mode and restore footer
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

    def _update_saved_query_footer(self) -> None:
        """Update the footer to show saved-query slot mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one(  # type: ignore[attr-defined]
                "#keybinding-footer", KeybindingFooter
            )
            footer.update_saved_query_bindings()
        except Exception:
            pass

    def action_open_saved_query_picker(self) -> None:
        """Open the cached saved-query chooser on the Artifacts PRs pane."""
        if (
            self.current_tab != "artifacts"
            or getattr(self, "current_artifacts_subtab", "prs") != "prs"
        ):
            return

        from ...modals import SavedQueryPickerModal

        def _load_slot(slot: str | None) -> None:
            if slot is not None:
                self._load_saved_query(slot)

        self.push_screen(  # type: ignore[attr-defined]
            SavedQueryPickerModal(
                dict(self._saved_queries),
                self.canonical_query_string,  # type: ignore[attr-defined]
            ),
            _load_slot,
        )

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
        from ....query import parse_query
        from ....query_history import navigate_prev, save_query_history

        if self.current_tab != "artifacts":
            return

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        prev_query = navigate_prev(current_canonical, self._query_history)
        if prev_query is None:
            self.notify("No previous query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = parse_query(prev_query)
            self.query_string = prev_query
            self._load_query_patches()
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def action_next_query(self) -> None:
        """Navigate to next query in history (_ key)."""
        from ....query import parse_query
        from ....query_history import navigate_next, save_query_history

        if self.current_tab != "artifacts":
            return

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        next_query = navigate_next(current_canonical, self._query_history)
        if next_query is None:
            self.notify("No next query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = parse_query(next_query)
            self.query_string = next_query
            self._load_query_patches()
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]
