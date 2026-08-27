"""App-level link-graph subject resolution and O(1) edge lookup."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..relations.artifact_links import load_artifact_links_snapshot
from ..relations.link_index import LinkChip, LinkIndex, link_index_for_snapshot
from ..relations.link_subject import LinkSubject, selected_link_subject
from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)


class LinkSubjectMixin:
    """Resolve the selected entity's link-graph subject and its edges.

    One projection point shared by every tab (bead:sase-ug.5): the rail,
    ``$``, and the ``$0`` panel all read through :meth:`link_edges_for_selection`
    instead of resolving a subject or scanning the aggregate themselves.
    """

    current_tab: Any
    _link_index: LinkIndex | None
    _link_index_errors: tuple[str, ...]
    _link_index_loading: bool
    _link_index_pending: bool
    _link_index_generation: int

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        """Return the ordered link chips for the currently selected entity.

        Empty when the current row cannot be resolved to a link-graph
        subject at all, or resolves to one with no recorded edges -- the
        same "nothing to show" state, by design (see the rail's
        invisibility contract).
        """

        subject: LinkSubject | None = selected_link_subject(self)
        if subject is None:
            return ()
        index: LinkIndex | None = getattr(self, "_link_index", None)
        if index is None:
            self._schedule_link_index_refresh(source="selection")
            return ()
        return index.chips_for(subject.ref)

    def refresh_link_rail(self) -> None:
        """Refresh the mounted rail from the current selection, if present."""

        from textual.css.query import NoMatches

        from ..link_rail_flag import link_rail_enabled
        from ..widgets import LinkRail

        rail = getattr(self, "_w_link_rail", None)
        if not isinstance(rail, LinkRail):
            try:
                rail = self.query_one("#link-rail", LinkRail)  # type: ignore[attr-defined]
            except NoMatches:
                return
            self._w_link_rail = rail
        if not link_rail_enabled():
            rail.clear()
            return
        if getattr(self, "_link_index", None) is None:
            rail.clear()
            self._schedule_link_index_refresh(source="rail")
            return
        rail.refresh_from_app(self)

    def _schedule_link_index_refresh(self, *, source: str) -> None:
        """Build or refresh the app-owned link index outside the message pump."""

        del source
        from ..link_rail_flag import link_rail_enabled

        if not link_rail_enabled():
            self._link_index = None
            self._link_index_errors = ()
            self._link_index_loading = False
            self._link_index_pending = False
            return
        if getattr(self, "_link_index_loading", False):
            self._link_index_pending = True
            return
        self._link_index_loading = True
        self._link_index_pending = False
        self._link_index_generation = getattr(self, "_link_index_generation", 0) + 1
        generation = self._link_index_generation

        async def _refresh() -> None:
            try:
                snapshot = await asyncio.to_thread(load_artifact_links_snapshot, None)
                index = await asyncio.to_thread(link_index_for_snapshot, snapshot)
            except Exception:
                log.exception("link rail index refresh failed")
                if generation == getattr(self, "_link_index_generation", None):
                    self._link_index_loading = False
                return
            if generation != getattr(self, "_link_index_generation", None):
                return
            self._link_index = index
            self._link_index_errors = snapshot.errors
            self._link_index_loading = False
            refresh_rail = getattr(self, "refresh_link_rail", None)
            if callable(refresh_rail):
                refresh_rail()
            if getattr(self, "_link_index_pending", False):
                self._schedule_link_index_refresh(source="pending")

        task = spawn_pump_free_task(
            self,
            _refresh(),
            name="sase-link-rail-index",
            registry_attr="_link_rail_tasks",
        )
        if task is None:
            self._link_index_loading = False


__all__ = ["LinkSubjectMixin"]
