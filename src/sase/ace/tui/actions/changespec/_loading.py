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
    _changespecs_last_idx: int
    _changespecs_last_name: str | None
    _all_changespecs: list[ChangeSpec]
    _hidden_reverted_count: int
    _query_reverted_count: int
    _hidden_submitted_count: int
    _query_submitted_count: int
    _changespecs_loading: bool
    _changespecs_refresh_pending: bool
    _current_changespec_group_key: tuple[str, ...] | None

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

        if current_name is None:
            current_name = self._snapshot_active_changespec_name()

        all_changespecs = find_all_changespecs_cached()
        self._apply_reloaded_changespecs(all_changespecs, current_name)

    def _snapshot_active_changespec_name(self) -> str | None:
        """Return the identity of the currently selected ChangeSpec.

        Falls back to ``_changespecs_last_name`` when the ChangeSpecs tab
        isn't active so off-tab refreshes (file-watcher / async reload
        while on Agents or AXE) restore by identity rather than by the
        cross-tab-shared ``current_idx``.
        """
        on_changespecs_tab = getattr(self, "current_tab", None) == "changespecs"
        if on_changespecs_tab and self.changespecs:
            idx = min(self.current_idx, len(self.changespecs) - 1)
            return self.changespecs[idx].name
        return getattr(self, "_changespecs_last_name", None)

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
        if not caller_supplied_name:
            current_name = self._snapshot_active_changespec_name()

        self._apply_reloaded_changespecs(all_changespecs, current_name)

    def _apply_reloaded_changespecs(
        self,
        all_changespecs: list[ChangeSpec],
        current_name: str | None,
    ) -> None:
        """Apply a freshly-loaded changespec list and reposition the cursor."""
        from ...util.selection import restore_selection_by_identity

        on_changespecs_tab = getattr(self, "current_tab", None) == "changespecs"

        self._all_changespecs = all_changespecs  # Cache for ancestry lookup
        new_changespecs = self._filter_changespecs(all_changespecs)

        # Capture the prior visual row before mutating state so we can
        # land on the nearest neighbor when the previously selected
        # ChangeSpec has been filtered out (Submitted + hide_submitted).
        if on_changespecs_tab:
            prior_visual_row = self.current_idx if self.changespecs else None
        else:
            prior_visual_row = getattr(self, "_changespecs_last_idx", None)

        # Try to find the same changespec by name. When the name was mutated
        # by a suffix strip/append (e.g. revert flow), fall back to the base
        # name before deferring to the neighbor-based helper.
        identity_to_match: str | None = current_name
        if current_name:
            found = any(cs.name == current_name for cs in new_changespecs)
            if not found:
                from sase.core.changespec import strip_reverted_suffix

                base = strip_reverted_suffix(current_name)
                if any(cs.name == base for cs in new_changespecs):
                    identity_to_match = base
                else:
                    for cs in new_changespecs:
                        if strip_reverted_suffix(cs.name) == base:
                            identity_to_match = cs.name
                            break

        new_idx = restore_selection_by_identity(
            new_changespecs,
            prior_identity=identity_to_match,
            prior_visual_row=prior_visual_row,
            identity_fn=lambda cs: cs.name,
        )

        self.changespecs = new_changespecs  # type: ignore[assignment]
        if on_changespecs_tab:
            self.current_idx = new_idx
        else:
            # Off-tab refresh: don't mutate ``current_idx`` (it belongs to
            # whichever tab is active). Update the saved row + identity
            # so a tab switch back lands on the right entry.
            self._changespecs_last_idx = new_idx
            if new_changespecs and 0 <= new_idx < len(new_changespecs):
                self._changespecs_last_name = new_changespecs[new_idx].name
            else:
                self._changespecs_last_name = None
        # Drop stale CL banner focus when its group's last member dropped
        # out of the filtered set — ``_refresh_display`` will also call
        # ``clear_unknown`` on the fold registry, but the focused banner
        # key has to be cleared here so the renderer doesn't try to
        # highlight a banner that no longer exists.
        if not self._changespec_banner_focus_still_valid():  # type: ignore[attr-defined]
            self._current_changespec_group_key = None  # type: ignore[attr-defined]
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
