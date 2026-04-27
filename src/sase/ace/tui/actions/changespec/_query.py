"""Saved-query slots and query-history navigation for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks

from ....changespec import ChangeSpec

TabName = Literal["changespecs", "agents", "axe"]


class ChangeSpecQueryMixin:
    """Mixin providing saved-query slot loading and history navigation."""

    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    parsed_query: QueryExpr
    query_string: str
    _all_changespecs: list[ChangeSpec]
    _query_history: QueryHistoryStacks
    _query_selections: dict[str, str]

    def _save_current_query(self) -> None:
        """Save the current query as the last used query."""
        from ....saved_queries import save_last_query

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

        from ....query import parse_query, to_canonical_string
        from ....query_history import push_to_prev_stack, save_query_history
        from ....saved_queries import load_saved_queries

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
                self._save_selection_for_current_query()  # type: ignore[attr-defined]
                push_to_prev_stack(current_canonical, self._query_history)
                save_query_history(self._query_history)

            self.parsed_query = new_parsed
            self.query_string = query
            self._load_changespecs()  # type: ignore[attr-defined]
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    async def _try_startup_fallback_async(self) -> bool:
        """Try saved queries as fallback when the startup query has no results.

        Async variant used by ``on_mount`` so the event loop is free between
        the saved-query load and the changespec re-read — lets the startup
        stopwatch tick. Checks slots 1-9 then 0. If a saved query produces
        results, switches to it and returns True. Returns False if no saved
        query has results.
        """
        import asyncio

        from ....query import parse_query, to_canonical_string
        from ....saved_queries import load_saved_queries

        queries = await asyncio.to_thread(load_saved_queries)
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
                filtered = self._filter_changespecs(self._all_changespecs)  # type: ignore[attr-defined]
                if filtered:
                    # Already-loaded list — re-reading from disk would be a
                    # ~37ms duplicate parse plus a second filter pass.
                    self._apply_changespecs(self._all_changespecs)  # type: ignore[attr-defined]
                    self._restore_selection_for_current_query()  # type: ignore[attr-defined]
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
        from ....query import parse_query
        from ....query_history import navigate_prev, save_query_history

        if self.current_tab != "changespecs":
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
            self._load_changespecs()  # type: ignore[attr-defined]
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def action_next_query(self) -> None:
        """Navigate to next query in history (_ key)."""
        from ....query import parse_query
        from ....query_history import navigate_next, save_query_history

        if self.current_tab != "changespecs":
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
            self._load_changespecs()  # type: ignore[attr-defined]
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(self._query_history)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]
