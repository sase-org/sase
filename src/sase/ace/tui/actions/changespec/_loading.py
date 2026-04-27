"""ChangeSpec loading, filtering, and reload logic for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....query.types import QueryExpr

from ....changespec import ChangeSpec
from ...util.trace import tui_trace


class ChangeSpecLoadingMixin:
    """Mixin providing changespec loading, filtering, and reload methods."""

    changespecs: list[ChangeSpec]
    current_idx: int
    parsed_query: QueryExpr
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _all_changespecs: list[ChangeSpec]
    _hidden_reverted_count: int
    _query_reverted_count: int
    _hidden_submitted_count: int
    _query_submitted_count: int
    _changespecs_loading: bool
    _changespecs_refresh_pending: bool

    def _read_changespecs_from_disk(self) -> list[ChangeSpec]:
        """Return the full changespec list freshly read from disk.

        Pure disk I/O with no widget access — safe to call from a worker
        thread via ``asyncio.to_thread`` so the Textual event loop stays
        free (e.g. for the startup stopwatch to tick).
        """
        from ....changespec import find_all_changespecs_cached

        return find_all_changespecs_cached()

    def _apply_changespecs(self, all_changespecs: list[ChangeSpec]) -> None:
        """Apply a pre-loaded changespec list to app state.

        Must run on the main thread: touches widgets via
        ``_update_cls_tab_count`` / ``_refresh_display``.
        """
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

        self._update_cls_tab_count()  # type: ignore[attr-defined]
        self._refresh_display()  # type: ignore[attr-defined]

    def _load_changespecs(self) -> None:
        """Load and filter changespecs from disk."""
        self._apply_changespecs(self._read_changespecs_from_disk())

    def _filter_changespecs(self, changespecs: list[ChangeSpec]) -> list[ChangeSpec]:
        """Filter changespecs using the parsed query and hide settings."""
        with tui_trace("changespec.filter", count=len(changespecs)):
            return self._filter_changespecs_impl(changespecs)

    def _filter_changespecs_impl(
        self, changespecs: list[ChangeSpec]
    ) -> list[ChangeSpec]:
        from ....changespec import get_base_status
        from ....query import build_query_context, evaluate_query_with_context
        from ....query.evaluator import (
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )

        # Build context once per refresh: name_map, status_map, plus
        # lazy searchable_text / ancestor_memo reused across rows.
        ctx = build_query_context(changespecs)
        status_map = ctx.status_map

        # First apply the query filter
        result = [
            cs
            for cs in changespecs
            if evaluate_query_with_context(self.parsed_query, cs, ctx)
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
            and not query_explicitly_targets_terminal(
                self.parsed_query, changespecs, status_map=status_map
            )
        )
        effective_hide_submitted = (
            self.hide_submitted
            and not query_explicitly_targets_submitted(
                self.parsed_query, changespecs, status_map=status_map
            )
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
        from ....changespec import find_all_changespecs_cached

        if current_name is None and self.changespecs:
            idx = min(self.current_idx, len(self.changespecs) - 1)
            current_name = self.changespecs[idx].name

        all_changespecs = find_all_changespecs_cached()
        self._apply_reloaded_changespecs(all_changespecs, current_name)

    async def _reload_and_reposition_async(
        self, current_name: str | None = None
    ) -> None:
        """Async variant of _reload_and_reposition.

        Off-loads the disk scan to a background thread and re-captures UI
        state after the await so the load survives user navigation while
        the I/O is in flight.
        """
        import asyncio

        from ....changespec import find_all_changespecs_cached

        caller_supplied_name = current_name is not None

        all_changespecs = await asyncio.to_thread(find_all_changespecs_cached)

        # Re-capture current selection AFTER the await — user may have
        # moved with j/k or switched tabs while disk I/O was in flight.
        # Skip if the caller explicitly pinned us to a specific name.
        if not caller_supplied_name and self.changespecs:
            idx = min(self.current_idx, len(self.changespecs) - 1)
            current_name = self.changespecs[idx].name

        self._apply_reloaded_changespecs(all_changespecs, current_name)

    def _apply_reloaded_changespecs(
        self,
        all_changespecs: list[ChangeSpec],
        current_name: str | None,
    ) -> None:
        """Apply a freshly-loaded changespec list and reposition the cursor."""
        self._all_changespecs = all_changespecs  # Cache for ancestry lookup
        new_changespecs = self._filter_changespecs(all_changespecs)

        # Try to find the same changespec by name
        new_idx = 0
        if current_name:
            for idx, cs in enumerate(new_changespecs):
                if cs.name == current_name:
                    new_idx = idx
                    break
            else:
                # Name changed (suffix strip/append) -- match by base name
                from sase.core.changespec import strip_reverted_suffix

                base = strip_reverted_suffix(current_name)
                # Prefer exact base name (suffix was stripped)
                for idx, cs in enumerate(new_changespecs):
                    if cs.name == base:
                        new_idx = idx
                        break
                else:
                    # Try any CS with same base name (suffix was appended)
                    for idx, cs in enumerate(new_changespecs):
                        if strip_reverted_suffix(cs.name) == base:
                            new_idx = idx
                            break

        self.changespecs = new_changespecs  # type: ignore[assignment]
        self.current_idx = new_idx
        self._update_cls_tab_count()  # type: ignore[attr-defined]
        self._refresh_display()  # type: ignore[attr-defined]

    def _schedule_changespecs_async_refresh(self) -> None:
        """Schedule an async changespec reload without blocking.

        Mirrors the agents-tab pattern: if a refresh is already in flight,
        mark a pending follow-up so the in-flight run re-schedules itself
        once it finishes (last-request-wins, collapses stampedes).
        """
        if self._changespecs_loading:
            self._changespecs_refresh_pending = True
            return
        self.call_later(self._run_changespecs_async_refresh)  # type: ignore[attr-defined]

    async def _run_changespecs_async_refresh(self) -> None:
        """Run the async changespec refresh with loading guard."""
        if self._changespecs_loading:
            self._changespecs_refresh_pending = True
            return
        self._changespecs_loading = True
        try:
            await self._reload_and_reposition_async()
        finally:
            self._changespecs_loading = False
            if self._changespecs_refresh_pending:
                self._changespecs_refresh_pending = False
                self.call_later(self._run_changespecs_async_refresh)  # type: ignore[attr-defined]
