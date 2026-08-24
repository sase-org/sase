"""Saved-query slots and query-history navigation for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ....query_record import QueryRecord

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
    _query_history: dict[str, QueryHistoryStacks]
    _query_selections: dict[str, dict[str, str]]
    _saved_queries: dict[str, dict[str, QueryRecord]]
    _patch_query_scope_seed_baseline: str | None

    def _save_current_query(self) -> None:
        """Save the current query as the last used query."""
        from ....saved_queries import save_last_query

        save_last_query(self.canonical_query_string)  # type: ignore[attr-defined]
        self._patch_query_scope_seed_baseline = None

    def _save_startup_query(self) -> None:
        """Persist the pre-seed query so a current-project seed never sticks."""
        from ....saved_queries import save_last_query

        baseline = self._patch_query_scope_seed_baseline
        save_last_query(
            baseline if baseline is not None else self.canonical_query_string  # type: ignore[attr-defined]
        )

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

    def _record_patch_query_transition(self, new_canonical: str) -> None:
        """Record the current Patch query before replacing it."""
        from ....query_history import (
            QueryHistoryStacks,
            push_to_prev_stack,
            save_query_history,
        )
        from ....query_record import QueryRecord, current_profile_digest

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        if new_canonical == current_canonical:
            return
        pane_id = "patches"
        recorder = getattr(self, "_record_artifacts_query_transition", None)
        if callable(recorder):
            pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
            selected = None
            if pane is not None:
                selected_entry = getattr(pane, "selected_entry_target", None)
                selected = selected_entry() if callable(selected_entry) else None
            recorder(
                pane_id,
                old_source=self.query_string,
                old_canonical=current_canonical,
                old_profile_digest=current_profile_digest(pane_id),
                new_canonical=new_canonical,
                selected_target=selected,
            )
            return

        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        current_record = QueryRecord(
            source=self.query_string,
            canonical=current_canonical,
            profile_digest=current_profile_digest(pane_id),
        )
        stacks = self._query_history.setdefault(
            pane_id, QueryHistoryStacks(prev=[], next=[])
        )
        push_to_prev_stack(current_record, stacks)
        save_query_history(pane_id, stacks)

    def _load_saved_query(self, slot: str) -> None:
        """Load a saved query from a slot on the active Artifacts pane.

        Saved-query slots are namespaced per pane. A call from outside the
        Artifacts tab entirely (e.g. an Agents keymap or the command
        palette) still lands on the Patches pane, since there's no
        "active Artifacts pane" to respect until the Artifacts tab is
        showing. A call made while already on the Artifacts tab no longer
        force-switches the sub-tab: loading always targets whichever pane
        is currently active. Only the Patches pane applies a loaded slot
        today (the other panes' own filter sessions aren't wired onto this
        mechanism yet), so pressing a slot key on another pane just
        reports that pane's own (currently empty) namespace.
        """
        if self.current_tab != "artifacts":
            self._save_current_tab_position()  # type: ignore[attr-defined]
            from ...artifact_tabs import switch_to_artifacts_subtab

            switch_to_artifacts_subtab(self, "patches")

        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        if pane_id != "patches":
            self.notify(f"No query saved in slot {slot}", severity="warning")  # type: ignore[attr-defined]
            return

        queries = self._saved_queries.get(pane_id, {})
        if slot not in queries:
            self.notify(f"No query saved in slot {slot}", severity="warning")  # type: ignore[attr-defined]
            return

        record = queries[slot]
        if record.is_stale(pane_id):
            self.notify(  # type: ignore[attr-defined]
                f"Slot {slot}'s saved query no longer matches this pane's "
                f"query dialect and needs review: {record.source}",
                severity="error",
            )
            return

        try:
            new_parsed = self._parse_patch_query(record.source)  # type: ignore[attr-defined]
            new_canonical = self._canonical_patch_query(  # type: ignore[attr-defined]
                record.source, new_parsed
            )

            # Only push to history if query actually changes
            self._record_patch_query_transition(new_canonical)

            self.parsed_query = new_parsed
            self.query_string = record.source
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
        """Open the cached saved-query chooser on the active Artifacts pane."""
        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        if self.current_tab != "artifacts" or pane_id != "patches":
            return

        from ...modals import SavedQueryPickerModal

        def _load_slot(slot: str | None) -> None:
            if slot is not None:
                self._load_saved_query(slot)

        queries = {
            slot: record.canonical
            for slot, record in self._saved_queries.get(pane_id, {}).items()
        }
        self.push_screen(  # type: ignore[attr-defined]
            SavedQueryPickerModal(
                queries,
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
        from ....query_history import (
            QueryHistoryStacks,
            navigate_prev,
            save_query_history,
        )
        from ....query_record import QueryRecord

        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        if self.current_tab != "artifacts" or pane_id != "patches":
            return

        current_record = QueryRecord(
            source=self.query_string,
            canonical=self.canonical_query_string,  # type: ignore[attr-defined]
        )
        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        stacks = self._query_history.setdefault(
            pane_id, QueryHistoryStacks(prev=[], next=[])
        )
        prev_record = navigate_prev(current_record, stacks)
        if prev_record is None:
            self.notify("No previous query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = self._parse_patch_query(prev_record.source)  # type: ignore[attr-defined]
            self.query_string = prev_record.source
            self._load_query_patches()
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(pane_id, stacks)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]

    def action_next_query(self) -> None:
        """Navigate to next query in history (_ key)."""
        from ....query_history import (
            QueryHistoryStacks,
            navigate_next,
            save_query_history,
        )
        from ....query_record import QueryRecord

        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        if self.current_tab != "artifacts" or pane_id != "patches":
            return

        current_record = QueryRecord(
            source=self.query_string,
            canonical=self.canonical_query_string,  # type: ignore[attr-defined]
        )
        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        stacks = self._query_history.setdefault(
            pane_id, QueryHistoryStacks(prev=[], next=[])
        )
        next_record = navigate_next(current_record, stacks)
        if next_record is None:
            self.notify("No next query", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self.parsed_query = self._parse_patch_query(next_record.source)  # type: ignore[attr-defined]
            self.query_string = next_record.source
            self._load_query_patches()
            self._restore_selection_for_current_query()  # type: ignore[attr-defined]
            self._save_current_query()
            save_query_history(pane_id, stacks)
        except Exception as e:
            self.notify(f"Error loading query: {e}", severity="error")  # type: ignore[attr-defined]
