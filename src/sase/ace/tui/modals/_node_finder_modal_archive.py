"""Warm-corpus Archive search for the Node Finder modal."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from ..models.node_finder import NodeFinderRole, NodeFinderRow, NodeFinderView
from ..util.pump_tasks import spawn_pump_free_task

if TYPE_CHECKING:
    from ..actions.agents._node_finder_archive import ArchiveNameCandidate

_TASKS_ATTR = "_node_finder_archive_tasks"


class NodeFinderArchiveMixin:
    """Append up to five asynchronously searched archived names to the view."""

    _archive_name_loader: Callable[[], tuple[ArchiveNameCandidate, ...]] | None
    _archive_candidates: tuple[ArchiveNameCandidate, ...]
    _archive_matches: tuple[ArchiveNameCandidate, ...]
    _archive_ready: bool
    _archive_message: str
    _archive_load_generation: int
    _archive_search_generation: int
    _view: NodeFinderView
    _live_view: NodeFinderView

    def _archive_call_next(
        self, callback: Callable[..., object], *args: object
    ) -> None:
        call_next = getattr(self, "call_next", None)
        if callable(call_next):
            call_next(callback, *args)

    def _init_archive_search(
        self,
        *,
        archive_name_loader: Callable[[], tuple[ArchiveNameCandidate, ...]] | None,
    ) -> None:
        self._archive_name_loader = archive_name_loader
        self._archive_candidates = ()
        self._archive_matches = ()
        self._archive_ready = False
        self._archive_message = "Archive warming…"
        self._archive_load_generation = 0
        self._archive_search_generation = 0

    def _start_archive_name_load(self) -> None:
        if self._archive_name_loader is None:
            return
        self._archive_load_generation += 1
        generation = self._archive_load_generation
        loader = self._archive_name_loader

        async def _load() -> None:
            try:
                candidates = await asyncio.to_thread(loader)
            except Exception:
                self._archive_call_next(
                    self._finish_archive_name_load, generation, (), False
                )
                return
            self._archive_call_next(
                self._finish_archive_name_load,
                generation,
                candidates,
                True,
            )

        spawn_pump_free_task(
            self,
            _load(),
            name="sase-node-finder-archive-load",
            registry_attr=_TASKS_ATTR,
        )

    def _finish_archive_name_load(
        self,
        generation: int,
        candidates: tuple[ArchiveNameCandidate, ...],
        succeeded: bool,
    ) -> None:
        if (
            not self.is_mounted  # type: ignore[attr-defined]
            or generation != self._archive_load_generation
        ):
            return
        if not succeeded:
            self._archive_message = "Archive unavailable."
            self._refresh_archive_projection()
            return
        self._archive_candidates = candidates
        self._archive_ready = True
        self._schedule_archive_search(self._live_view.query)  # type: ignore[attr-defined]

    def _schedule_archive_search(self, query: str) -> None:
        self._archive_search_generation += 1
        generation = self._archive_search_generation
        if not self._archive_ready:
            self._archive_matches = ()
            self._archive_message = "Archive warming…"
            self._refresh_archive_projection()
            return
        candidates = self._archive_candidates

        async def _search() -> None:
            try:
                from ..actions.agents._node_finder_archive import (
                    search_archive_name_candidates,
                )

                matches = await asyncio.to_thread(
                    search_archive_name_candidates,
                    candidates,
                    query,
                )
            except Exception:
                self._archive_call_next(
                    self._finish_archive_search,
                    generation,
                    query,
                    (),
                    False,
                )
                return
            self._archive_call_next(
                self._finish_archive_search,
                generation,
                query,
                matches,
                True,
            )

        spawn_pump_free_task(
            self,
            _search(),
            name="sase-node-finder-archive-search",
            registry_attr=_TASKS_ATTR,
        )
        self._archive_message = "Searching Archive…"
        self._archive_matches = ()
        self._refresh_archive_projection()

    def _finish_archive_search(
        self,
        generation: int,
        query: str,
        matches: tuple[ArchiveNameCandidate, ...],
        succeeded: bool,
    ) -> None:
        if (
            not self.is_mounted  # type: ignore[attr-defined]
            or generation != self._archive_search_generation
            or query != self._live_view.query  # type: ignore[attr-defined]
        ):
            return
        self._archive_matches = matches if succeeded else ()
        self._archive_message = (
            "No archived name matches." if succeeded else "Archive unavailable."
        )
        self._refresh_archive_projection()

    def _compose_archive_view(self) -> NodeFinderView:
        """Project Archive rows after the live rows without adding hints."""
        live_view = self._live_view  # type: ignore[attr-defined]
        rows = list(live_view.rows)
        rows.append(NodeFinderRow(role=NodeFinderRole.ARCHIVE_HEADER))
        archive_start = len(rows)
        if self._archive_matches:
            for candidate in self._archive_matches:
                rows.append(
                    NodeFinderRow(
                        role=NodeFinderRole.ARCHIVE_RESULT,
                        name=candidate.name,
                        archive_name=candidate.name,
                        archive_row=candidate.row,
                        archive_status=candidate.status,
                        archive_model=candidate.model,
                        archive_outcome=candidate.outcome,
                        jumpable=True,
                    )
                )
        else:
            rows.append(
                NodeFinderRow(
                    role=NodeFinderRole.ARCHIVE_MESSAGE,
                    name=self._archive_message,
                )
            )
        best_index = live_view.best_index
        if best_index is None and self._archive_matches:
            best_index = archive_start
        return replace(live_view, rows=tuple(rows), best_index=best_index)

    def _refresh_archive_projection(self) -> None:
        if not self.is_mounted:  # type: ignore[attr-defined]
            return
        old_index = self._highlighted_view_index()  # type: ignore[attr-defined]
        old_row = (
            self._view.rows[old_index]
            if old_index is not None and 0 <= old_index < len(self._view.rows)  # type: ignore[attr-defined]
            else None
        )
        self._view = self._compose_archive_view()  # type: ignore[attr-defined]
        highlight = self._view.best_index  # type: ignore[attr-defined]
        if old_row is not None:
            for index, row in enumerate(self._view.rows):  # type: ignore[attr-defined]
                if (
                    old_row.identity is not None and row.identity == old_row.identity
                ) or (
                    old_row.archive_name is not None
                    and row.archive_name == old_row.archive_name
                ):
                    highlight = index
                    break
        self._rebuild_options(highlight=highlight)  # type: ignore[attr-defined]
        self._paint_chrome()  # type: ignore[attr-defined]
        self._paint_preview()  # type: ignore[attr-defined]


__all__ = ["NodeFinderArchiveMixin"]
