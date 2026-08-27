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
    _link_follow_available_cache: tuple[tuple[object, ...], bool] | None

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        """Return the ordered link chips for the currently selected entity.

        Empty when the current row cannot be resolved to a link-graph
        subject at all, or resolves to one with no recorded edges -- the
        same "nothing to show" state, by design (see the rail's
        invisibility contract).
        """

        subject: LinkSubject | None = selected_link_subject(self)
        if subject is None:
            self._cache_link_follow_available(False)
            return ()
        index: LinkIndex | None = getattr(self, "_link_index", None)
        if index is None:
            self._schedule_link_index_refresh(source="selection")
            if getattr(self, "_link_index_loading", False):
                self._cache_link_follow_available(False)
            return ()
        chips = index.chips_for(subject.ref)
        self._cache_link_follow_available(bool(chips))
        return chips

    def link_follow_available_for_selection(self) -> bool:
        """Return whether the current selection has any followable link chips."""

        cache_key = self._link_follow_available_cache_key()
        cached = getattr(self, "_link_follow_available_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        subject: LinkSubject | None = selected_link_subject(self)
        if subject is None:
            self._cache_link_follow_available(False)
            return False
        index: LinkIndex | None = getattr(self, "_link_index", None)
        if index is None:
            self._schedule_link_index_refresh(source="availability")
            if getattr(self, "_link_index_loading", False):
                self._cache_link_follow_available(False)
            return False
        available = bool(index.chips_for(subject.ref))
        self._cache_link_follow_available(available)
        return available

    def _cache_link_follow_available(self, value: bool) -> None:
        self._link_follow_available_cache = (
            self._link_follow_available_cache_key(),
            value,
        )

    def _link_follow_available_cache_key(self) -> tuple[object, ...]:
        tab = str(getattr(self, "current_tab", ""))
        index = getattr(self, "_link_index", None)
        base: tuple[object, ...] = (
            tab,
            getattr(self, "_link_index_generation", 0),
            id(index),
        )
        if tab == "agents":
            return (
                *base,
                getattr(self, "current_idx", None),
                *_selected_agent_key(self),
            )
        if tab == "artifacts":
            return (
                *base,
                str(getattr(self, "current_artifacts_pane_key", "")),
                _selected_artifacts_target_key(self),
            )
        if tab == "axe":
            return (
                *base,
                getattr(self, "current_idx", None),
                _selected_axe_item_key(self),
            )
        return base

    def refresh_link_rail(self) -> None:
        """Refresh the mounted rail from the current selection, if present."""

        from textual.css.query import NoMatches

        from ..widgets import LinkRail

        rail = getattr(self, "_w_link_rail", None)
        if not isinstance(rail, LinkRail):
            try:
                rail = self.query_one("#link-rail", LinkRail)  # type: ignore[attr-defined]
            except NoMatches:
                return
            self._w_link_rail = rail
        if getattr(self, "_link_index", None) is None:
            rail.clear()
            self._schedule_link_index_refresh(source="rail")
            return
        rail.refresh_from_app(self)

    def _schedule_link_index_refresh(self, *, source: str) -> None:
        """Build or refresh the app-owned link index outside the message pump."""

        del source
        if getattr(self, "_link_index_loading", False):
            self._link_index_pending = True
            return
        self._link_index_loading = True
        self._link_index_pending = False
        self._link_index_generation = getattr(self, "_link_index_generation", 0) + 1
        self._link_follow_available_cache = None
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
            self._link_follow_available_cache = None
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


def _selected_agent_key(app: Any) -> tuple[object, ...]:
    resolver = getattr(app, "_get_selected_agent", None)
    if not callable(resolver):
        return (None, None)
    try:
        agent = resolver()
    except Exception:
        return (None, None)
    if agent is None:
        return (None, None)
    return (getattr(agent, "agent_name", None), getattr(agent, "identity", None))


def _selected_artifacts_target_key(app: Any) -> object:
    navigator = getattr(app, "_artifacts_entry_navigator", None)
    if not callable(navigator):
        return None
    try:
        pane = navigator()
    except Exception:
        return None
    if pane is None:
        return None
    selected = getattr(pane, "selected_entry_target", None)
    if not callable(selected):
        return None
    try:
        target = selected()
    except Exception:
        return None
    if target is None:
        return None
    to_token = getattr(target, "to_token", None)
    if callable(to_token):
        try:
            return to_token()
        except Exception:
            return target
    return target


def _selected_axe_item_key(app: Any) -> object:
    items = getattr(app, "_axe_items", None) or ()
    idx = getattr(app, "current_idx", -1)
    try:
        item = items[idx] if 0 <= idx < len(items) else None
    except Exception:
        return None
    return None if item is None else id(item)


__all__ = ["LinkSubjectMixin"]
