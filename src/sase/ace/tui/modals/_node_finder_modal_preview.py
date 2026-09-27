"""Two-tier preview painting for the Node Finder modal.

Moves Tier 0 (instant row render) plus the debounced Tier 1 loader out of
:class:`~sase.ace.tui.modals.node_finder_modal.NodeFinderModal` without
changing its behavior: the highlight still paints synchronously from the
memoized Tier 0 text, then the debounced worker fills in the Tier 1
prompt/reply payload when it lands for the still-current row.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from ..models.node_finder import (
    NodeFinderRow,
    NodeFinderSnapshot,
    NodeFinderView,
)
from ..util.debounce import DetailPanelDebouncer
from ..util.pump_tasks import spawn_pump_free_task
from ..util.trace import tui_trace
from .node_finder_preview import render_node_finder_preview
from .node_finder_preview_loader import (
    NodeFinderPreviewCache,
    NodeFinderPreviewPayload,
    render_tier1,
    tier1_source,
)
from .node_finder_rendering import EMPTY_PREVIEW

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.node_finder import AgentIdentity


class NodeFinderPreviewMixin:
    """Tier 0/1 preview painting for the Node Finder highlight."""

    _snapshot: NodeFinderSnapshot
    _view: NodeFinderView
    _cache: NodeFinderPreviewCache
    _tier0_cache: dict[tuple[object, ...], Text]
    _preview_generation: int
    _debouncer: DetailPanelDebouncer | None

    def _paint_preview(self) -> None:
        with tui_trace("node_finder.preview"):
            preview = self.query_one(  # type: ignore[attr-defined]
                "#node-finder-preview", Static
            )
            row = self._current_row()
            if row is None:
                preview.update(Text(EMPTY_PREVIEW, style="dim"))
                return
            payload = None
            source = tier1_source(row, self._snapshot)
            if source is not None:
                payload = self._cache.get(source.identity)
            preview.update(self._compose_preview(row, payload))
            self._schedule_tier1(row)

    def _tier0_cache_key(self, row: NodeFinderRow) -> tuple[object, ...]:
        """Return the Tier 0 cache key for *row*.

        The snapshot (and its query) is fixed for the modal lifetime and
        reasons never change within it, so the Tier 0 text depends only on
        which node or header the row shows.
        """
        identity = row.identity
        if identity is not None:
            return ("node", identity)
        return (
            "header",
            row.role.value,
            row.name,
            row.group_label,
            row.panel_key,
        )

    def _compose_preview(
        self,
        row: NodeFinderRow,
        payload: NodeFinderPreviewPayload | None,
    ) -> Text:
        key = self._tier0_cache_key(row)
        base = self._tier0_cache.get(key)
        if base is None:
            base = render_node_finder_preview(row, self._snapshot, self._snapshot.query)
            self._tier0_cache[key] = base
        if payload is None:
            return base
        cutoff = base.plain.rfind("PROMPT")
        combined = Text()
        if cutoff > 0:
            combined.append_text(base[:cutoff])
        combined.append_text(render_tier1(payload))
        return combined

    def _schedule_tier1(self, row: NodeFinderRow) -> None:
        source = tier1_source(row, self._snapshot)
        self._preview_generation += 1
        generation = self._preview_generation
        if source is None or self._debouncer is None:
            return
        identity = source.identity

        def _kick() -> None:
            spawn_pump_free_task(
                self,
                self._load_tier1(identity, generation),
                name="node-finder-preview",
                registry_attr="_node_finder_preview_tasks",
            )

        self._debouncer.schedule(_kick)

    async def _load_tier1(self, identity: AgentIdentity, generation: int) -> None:
        agent = self._agent_for(identity)
        if agent is None:
            return
        payload = await asyncio.to_thread(
            self._preview_loader,  # type: ignore[attr-defined]
            agent,
        )
        if generation != self._preview_generation:
            return
        current = self._current_row()
        if current is None or current.identity != identity:
            return
        self._cache.put(payload)
        self.query_one(  # type: ignore[attr-defined]
            "#node-finder-preview", Static
        ).update(self._compose_preview(current, payload))

    def _agent_for(self, identity: AgentIdentity) -> Agent | None:
        for row in self._snapshot.rows:
            if row.identity == identity:
                return row.agent
        return None

    def _current_row(self) -> NodeFinderRow | None:
        if not self.is_mounted:  # type: ignore[attr-defined]
            return None
        highlighted = self._highlighted_view_index()  # type: ignore[attr-defined]
        if highlighted is None or not (0 <= highlighted < len(self._view.rows)):
            return None
        return self._view.rows[highlighted]


__all__ = ["NodeFinderPreviewMixin"]
