"""App-side helpers for the inline Patch filter session."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ....patch import Patch
from ....query import QueryParseError, parse_query_for_profile, to_canonical_string
from ....query.limit_token import LimitTokenError, extract_limit, replace_limit
from ....query.types import StringMatch

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ....query_record import QueryRecord


class PatchFilterSessionActionsMixin:
    """Shared Patch query mutation helpers used by the inline filter bar."""

    patches: list[Patch]
    current_idx: int
    query_string: str
    parsed_query: QueryExpr
    _all_patches: list[Patch]
    _live_patch_query: tuple[str, QueryExpr] | None
    _current_patch_group_key: tuple[str, ...] | None
    _query_history: dict[str, QueryHistoryStacks]
    _saved_queries: dict[str, dict[str, QueryRecord]]
    _patch_query_scope_seed_attempted: bool
    _patch_query_scope_seed_baseline: str | None

    def action_patches_filters(self) -> None:
        """Open the inline Patch filter bar."""

        if (
            getattr(self, "current_tab", None) != "artifacts"
            or getattr(self, "current_artifacts_pane_key", "patches") != "patches"
        ):
            return
        pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
        show_filters = getattr(pane, "show_filters", None)
        if callable(show_filters):
            show_filters()

    def _parse_patch_query(self, source: str) -> QueryExpr:
        profile = self._patch_profile()  # type: ignore[attr-defined]
        try:
            remainder, _cap = extract_limit(source)
        except LimitTokenError as exc:
            raise QueryParseError(exc.message, exc.start) from exc
        if not remainder.strip():
            return StringMatch("")
        return parse_query_for_profile(remainder, profile)

    def _canonical_patch_query(self, source: str, parsed: QueryExpr) -> str:
        try:
            remainder, cap = extract_limit(source)
        except LimitTokenError:
            remainder, cap = source, None
        body = to_canonical_string(parsed) if remainder.strip() else ""
        if cap is None:
            return body
        return replace_limit(body, cap)

    def _display_patch_query(self) -> str:
        live = getattr(self, "_live_patch_query", None)
        return live[0] if live is not None else self.query_string

    def _display_patch_parsed_query(self) -> QueryExpr:
        live = getattr(self, "_live_patch_query", None)
        return live[1] if live is not None else self.parsed_query

    def _set_patch_live_query(self, source: str, parsed: QueryExpr) -> None:
        self._live_patch_query = (source, parsed)
        self._refilter_current_patch_snapshot()

    def _clear_patch_live_query(self) -> None:
        self._live_patch_query = None
        self._refilter_current_patch_snapshot()

    def _refilter_current_patch_snapshot(self) -> None:
        target = self._selected_patch_target()
        self.patches = self._filter_patches(self._all_patches)  # type: ignore[attr-defined]
        if target is not None and self._select_patch_target(target):
            pass
        elif self.patches:
            self.current_idx = min(max(self.current_idx, 0), len(self.patches) - 1)
        else:
            self.current_idx = 0
        if not self._patch_banner_focus_still_valid():  # type: ignore[attr-defined]
            self._current_patch_group_key = None  # type: ignore[attr-defined]
        self._refresh_display()  # type: ignore[attr-defined]

    def _commit_patch_query(self, source: str, *, notify: bool = True) -> None:
        from ....query_history import (
            QueryHistoryStacks,
            push_to_prev_stack,
            save_query_history,
        )
        from ....query_record import QueryRecord

        new_parsed = self._parse_patch_query(source)
        new_canonical = self._canonical_patch_query(source, new_parsed)
        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
        self._live_patch_query = None
        if new_canonical == current_canonical:
            if self._patch_query_scope_seed_baseline is not None:
                self._save_current_query()  # type: ignore[attr-defined]
            self._refresh_display()  # type: ignore[attr-defined]
            return

        pane_id = "patches"
        self._save_selection_for_current_query()  # type: ignore[attr-defined]
        current_record = QueryRecord(
            source=self.query_string,
            canonical=current_canonical,
        )
        stacks = self._query_history.setdefault(
            pane_id, QueryHistoryStacks(prev=[], next=[])
        )
        push_to_prev_stack(current_record, stacks)
        save_query_history(pane_id, stacks)

        self.query_string = source
        self.parsed_query = new_parsed
        self._load_patches()  # type: ignore[attr-defined]
        self._restore_selection_for_current_query()  # type: ignore[attr-defined]
        self._save_current_query()  # type: ignore[attr-defined]
        if notify:
            self.notify("Query updated")  # type: ignore[attr-defined]

    def _save_patch_query_slot(self, text: str) -> None:
        from ....saved_queries import (
            delete_query,
            find_slot_for_query,
            get_next_available_slot,
            load_saved_queries,
            save_query,
        )

        save_match = re.match(r"^#(\d)?(.*)$", text.strip())
        if save_match is None:
            return

        pane_id = "patches"
        slot_specified = save_match.group(1)
        query_part = save_match.group(2).strip()

        if not query_part:
            if slot_specified:
                if delete_query(pane_id, slot_specified):
                    self._invalidate_saved_queries_cache()  # type: ignore[attr-defined]
                    self._refresh_display()  # type: ignore[attr-defined]
                    self.notify(f"Deleted query from slot {slot_specified}")  # type: ignore[attr-defined]
                else:
                    self.notify("Failed to delete query", severity="error")  # type: ignore[attr-defined]
            else:
                self.notify("No slot specified to delete", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            parsed = self._parse_patch_query(query_part)
            canonical = self._canonical_patch_query(query_part, parsed)
        except (QueryParseError, ValueError) as exc:
            self.notify(f"Invalid query: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        existing_slot = find_slot_for_query(pane_id, canonical)
        if slot_specified:
            slot = slot_specified
        else:
            if existing_slot is not None:
                self.notify(f"Query already saved in slot {existing_slot}")  # type: ignore[attr-defined]
                return
            queries = load_saved_queries(pane_id)
            slot = get_next_available_slot(queries)
            if slot is None:
                self.notify("All 10 slots are full", severity="warning")  # type: ignore[attr-defined]
                return

        if save_query(pane_id, slot, query_part, canonical):
            self._invalidate_saved_queries_cache()  # type: ignore[attr-defined]
            self._refresh_display()  # type: ignore[attr-defined]
            if existing_slot is not None and existing_slot != slot:
                self.notify(  # type: ignore[attr-defined]
                    f"Moved query from slot {existing_slot} to slot {slot}: {canonical}"
                )
            else:
                self.notify(f"Saved to slot {slot}: {canonical}")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to save query", severity="error")  # type: ignore[attr-defined]

    def _selected_patch_target(self) -> tuple[str, str] | None:
        if not self.patches or not 0 <= self.current_idx < len(self.patches):
            return None
        patch = self.patches[self.current_idx]
        return (patch.project_name, patch.name)

    def _select_patch_target(self, target: tuple[str, str]) -> bool:
        for index, patch in enumerate(self.patches):
            if (patch.project_name, patch.name) != target:
                continue
            self.current_idx = index
            return True
        return False


__all__ = ["PatchFilterSessionActionsMixin"]
