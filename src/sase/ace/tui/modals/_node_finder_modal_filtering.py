"""Latest-wins refilter scheduling for the Node Finder modal.

Moves the coalesced query worker out of
:class:`~sase.ace.tui.modals.node_finder_modal.NodeFinderModal` without
changing its behavior: rapid keystrokes still collapse to a single list
rebuild for the final query, and Tab/Enter still flush through
:meth:`NodeFinderFilteringMixin._flush_pending_refilter` first.
"""

from __future__ import annotations

from textual.widgets import Input

from ..models.node_finder import (
    NodeFinderSnapshot,
    NodeFinderView,
    filter_node_finder,
)
from ..util.trace import tui_trace

#: Maximum memoized filtered views per modal. Repeated refilters of the
#: same query (the common case is a handful of recent queries) hit; the
#: bound keeps a broad whole-tree view plus a few narrow ones resident
#: without growing across opens, since the cache dies with the modal.
_VIEW_CACHE_SIZE = 8


class NodeFinderFilteringMixin:
    """Coalesced refilter and memoized filtered views for the Node Finder."""

    _snapshot: NodeFinderSnapshot
    _view: NodeFinderView
    _view_cache: dict[tuple[str, tuple[str, ...] | None], NodeFinderView]
    _pending: str
    _refilter_generation: int
    _pending_refilter_query: str | None

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "node-finder-query":
            return
        self._schedule_refilter(event.value)

    def _schedule_refilter(self, value: str) -> None:
        """Arm a latest-wins refilter; the keystroke callback stays thin.

        Rapid keystrokes supersede one another via the generation guard, so a
        burst collapses to a single list rebuild for the final query. Tab and
        Enter flush through :meth:`_flush_pending_refilter` first. The worker
        runs on the next message tick (no added delay); staleness is decided
        by generation, so no timer handle needs cancelling.
        """
        self._refilter_generation += 1
        generation = self._refilter_generation
        self._pending_refilter_query = value
        self.call_next(  # type: ignore[attr-defined]
            self._fire_scheduled_refilter, value, generation
        )

    def _fire_scheduled_refilter(self, query: str, generation: int) -> None:
        if self._pending_refilter_query == query:
            self._pending_refilter_query = None
        self._apply_refilter(query, generation)

    def _filtered_view(
        self, query: str, previous: NodeFinderView | None
    ) -> NodeFinderView:
        """Return the filtered view for *query*, reusing a memoized one.

        Views are never mutated after construction (refilters replace
        ``self._view`` and every row tuple is frozen), so sharing one
        across repeated refilters is exact. The previous view's tokens
        join the key so a refinement-narrowed evaluation and a full one
        for the same query never collide.
        """
        key = (query, previous.tokens if previous is not None else None)
        hit = self._view_cache.get(key)
        if hit is None:
            hit = filter_node_finder(self._snapshot, query, previous=previous)
            if len(self._view_cache) >= _VIEW_CACHE_SIZE:
                self._view_cache.pop(next(iter(self._view_cache)))
            self._view_cache[key] = hit
        return hit

    def _apply_refilter(self, query: str, generation: int) -> None:
        if generation != self._refilter_generation:
            return  # Superseded by a newer keystroke; latest wins.
        if not self.is_mounted:  # type: ignore[attr-defined]
            return
        with tui_trace("node_finder.filter"):
            self._view = self._filtered_view(query, self._view)
            self._pending = ""
            self._rebuild_options(  # type: ignore[attr-defined]
                highlight=self._view.best_index
            )
            self._paint_chrome()  # type: ignore[attr-defined]
            self._paint_preview()  # type: ignore[attr-defined]

    def _flush_pending_refilter(self) -> None:
        """Run any coalesced refilter now so Tab/Enter see the latest list.

        Bumping the generation first drops the still-queued scheduled worker
        when it fires.
        """
        if self._pending_refilter_query is None:
            return
        query = self._pending_refilter_query
        self._pending_refilter_query = None
        self._refilter_generation += 1
        self._apply_refilter(query, self._refilter_generation)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "node-finder-query":
            return
        self._jump_highlighted()  # type: ignore[attr-defined]


__all__ = ["NodeFinderFilteringMixin"]
