"""Paint-time rail projection for ``AgentList`` (rail-projection phase).

The rail is not a new widget: Textual's ``OptionList`` routes both height
arrangement (:meth:`_update_lines`) and painting (:meth:`_get_option_render`)
through :meth:`_get_visual`, so overriding that hook renders a fixed-width
rail visual for each existing ``Option``. The build, patch, and insert paths
stay untouched, and toggling the rail is a cache clear, not a rebuild.

The override never writes ``option._visual``: the expanded visual stays
cached for the toggle back. The rail cache is keyed by ``Option`` and holds
``(prompt, visual)``; an entry is valid only while
``entry.prompt is option.prompt``. Patches mutate the same ``Option``'s
prompt in place, so prompt identity is what busts a stale rail cell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.events import Leave, MouseMove, Resize
from textual.visual import Visual, visualize
from textual.widgets.option_list import Option

from ..util.trace import trace_event, tui_trace
from ._agent_list_render_rail import (
    RAIL_CONTENT_CELLS,
    rail_agent_cells,
    rail_banner_cells,
    rail_overflow_subtitle,
    rail_tooltip_text,
)
from ._agent_list_styling import BANNER_ROW
from ..models._agent_tree import agent_tree_depth

if TYPE_CHECKING:
    from ..models.agent_groups import GroupRow

__all__ = ["AgentListRailMixin"]


class AgentListRailMixin:
    """Paint-time rail render mode mixed into :class:`AgentList`.

    Not wired to any key yet: a later phase calls :meth:`set_rail` when the
    persisted sidebar preference says ``RAIL``. Requires the host widget to
    provide the ``AgentListBase`` row maps (``_option_to_index``,
    ``_row_entries``, ``_group_at_row``, ``_agents``, ``_row_render_ctx``,
    ``_grouping_mode``, ``_unread_agents``, ``_banner_hint_at_row``,
    ``_banner_mark_at_row``), ``_clear_caches()``, ``_rail_enabled`` /
    ``_rail_visual_cache`` / ``_rail_tooltip_index`` state, and the
    ``OptionList`` hover/tooltip surface (``_mouse_hovering_over``,
    ``get_option_at_index``, ``tooltip``).
    """

    _rail_enabled: bool
    _rail_overflow_plain: str
    _rail_tooltip_index: int | None
    _rail_visual_cache: dict[Option, tuple[Any, Visual]]
    # Host-provided Textual surface (typed loosely so this mixin stays
    # combinable without importing the widget hierarchy).
    border_subtitle: Any
    tooltip: Any

    def set_rail(self, enabled: bool) -> None:
        """Enable or disable rail projection without rebuilding the rows.

        No-op when unchanged. Stores the flag, toggles the ``-rail`` class,
        drops the rail cache, and clears the Textual caches so every row
        repaints in the new density. The same ``Option`` objects keep their
        highlight and scroll offset, and ``option._visual`` is untouched.
        """
        if enabled == self._rail_enabled:
            return
        with tui_trace("widget.agent_list.set_rail", enabled=enabled):
            self._rail_enabled = enabled
            self.set_class(enabled, "-rail")  # type: ignore[attr-defined]
            self._rail_visual_cache.clear()
            self._clear_caches()  # type: ignore[attr-defined]
            self._clear_rail_tooltip()
            self._refresh_rail_overflow()

    def _get_visual(self, option: Option) -> Visual:
        """Return the rail visual for *option* when the rail is on.

        Falls back to blank cells plus a trace event when the row maps are
        mid-update (the in-place insert path assigns them after
        ``install_options`` runs ``_update_lines``); the rows-changed hook
        drops the cache and repaints once the maps land. Never raises and
        never writes ``option._visual``.
        """
        if not self._rail_enabled:
            return super()._get_visual(option)  # type: ignore[misc]
        cached = self._rail_visual_cache.get(option)
        if cached is not None and cached[0] is option.prompt:
            return cached[1]
        try:
            cells: Text | None = self._rail_cells_for_option(option)
        except Exception:
            cells = None
        if cells is None:
            trace_event(
                "widget.agent_list.rail_fallback",
                option_id=getattr(option, "id", None),
            )
            return visualize(self, Text(" " * RAIL_CONTENT_CELLS), markup=False)  # type: ignore[arg-type]
        visual = visualize(self, cells, markup=False)  # type: ignore[arg-type]
        self._rail_visual_cache[option] = (option.prompt, visual)
        return visual

    def _rail_cells_for_option(self, option: Option) -> Text | None:
        """Build the fixed-width rail cells for *option*, or ``None``.

        ``None`` means the row maps do not cover this option yet (stale or
        mid-update maps, or rows without render context); the caller
        renders blank cells and traces a fallback. Spacer rows have no
        ``_group_at_row`` entry by design, so they are recognised by id and
        return blank cells directly instead of going through the fallback.
        Banner rows resolve through the all-banner ``_group_at_row`` map;
        agent rows through ``_agents``, ``_row_render_ctx``, and tree depth.
        """
        option_id = getattr(option, "id", None)
        if option_id is not None and option_id.startswith("spacer:"):
            return Text(" " * RAIL_CONTENT_CELLS)
        index = self._option_to_index.get(option)  # type: ignore[attr-defined]
        if index is None:
            return None
        entries = self._row_entries  # type: ignore[attr-defined]
        if not (0 <= index < len(entries)):
            return None
        local_idx, _attempt_number = entries[index]
        if local_idx == BANNER_ROW:
            group: GroupRow | None = self._group_at_row.get(index)  # type: ignore[attr-defined]
            if group is None:
                return None
            hint = self._banner_hint_at_row.get(index)  # type: ignore[attr-defined]
            mark_state = self._banner_mark_at_row.get(index, "none")  # type: ignore[attr-defined]
            return rail_banner_cells(
                group,
                self._agents,  # type: ignore[attr-defined]
                mode=self._grouping_mode,  # type: ignore[attr-defined]
                unread=self._unread_agents,  # type: ignore[attr-defined]
                hint=hint,
                mark_state=mark_state,
            )
        agents = self._agents  # type: ignore[attr-defined]
        if not (0 <= local_idx < len(agents)):
            return None
        ctx = self._row_render_ctx.get(local_idx)  # type: ignore[attr-defined]
        if ctx is None:
            return None
        try:
            depth = agent_tree_depth(agents[local_idx])
        except Exception:
            depth = 0
        return rail_agent_cells(agents[local_idx], ctx, depth=depth)

    def _rail_rows_changed(self) -> None:
        """Refresh rail caches after a structural path reassigned row maps.

        Called at the end of every structural path (full rebuild, in-place
        insert, optimistic remove, collapsed render) after all maps are
        assigned. When the rail is on it drops the rail cache and clears
        the Textual caches; the overflow subtitle refreshes either way.
        """
        if self._rail_enabled:
            self._rail_visual_cache.clear()
            self._clear_caches()  # type: ignore[attr-defined]
        self._refresh_rail_overflow()

    def _refresh_rail_overflow(self) -> None:
        """Publish the rail overflow subtitle from the current viewport.

        Shows ``▴N▾M`` for rows above and below the viewport while the rail
        is on, and clears the subtitle when it is off. Only writes when the
        text changes. The subtitle carries no spans, so the plain string is
        assigned directly (reading ``border_subtitle`` back gives markup).
        """
        if not self._rail_enabled:
            if self._rail_overflow_plain:
                self._rail_overflow_plain = ""
                self.border_subtitle = ""  # type: ignore[attr-defined]
            return
        try:
            offset_y = int(self.scroll_offset.y)  # type: ignore[attr-defined]
        except Exception:
            offset_y = 0
        try:
            total = int(self.virtual_size.height)  # type: ignore[attr-defined]
        except Exception:
            total = 0
        try:
            viewport = int(self.scrollable_content_region.height)  # type: ignore[attr-defined]
        except Exception:
            viewport = 0
        above = max(0, offset_y)
        below = max(0, total - offset_y - viewport)
        subtitle = rail_overflow_subtitle(above, below)
        plain = subtitle.plain
        if plain != self._rail_overflow_plain:
            self._rail_overflow_plain = plain
            self.border_subtitle = plain  # type: ignore[attr-defined]

    def _clear_rail_tooltip(self) -> None:
        """Drop the hover tooltip and its change guard."""
        self._rail_tooltip_index = None
        try:
            self.tooltip = None  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_mouse_move(self, event: MouseMove) -> None:
        """Show the hovered rail row's full expanded text as a tooltip.

        Runs after ``OptionList._on_mouse_move`` refreshes
        ``_mouse_hovering_over``. Only the hovered index change republishes
        the tooltip; when the rail is off the event passes through untouched.
        """
        super()._on_mouse_move(event)  # type: ignore[misc]
        if not self._rail_enabled:
            return
        hovered = self._mouse_hovering_over  # type: ignore[attr-defined]
        if hovered == self._rail_tooltip_index:
            return
        self._rail_tooltip_index = hovered
        if hovered is None:
            self._clear_rail_tooltip()
            return
        try:
            option = self.get_option_at_index(hovered)  # type: ignore[attr-defined]
        except Exception:
            self._clear_rail_tooltip()
            return
        try:
            self.tooltip = rail_tooltip_text(option.prompt)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_leave(self, event: Leave) -> None:
        """Clear the rail tooltip once the pointer leaves the list."""
        super()._on_leave(event)  # type: ignore[misc]
        self._clear_rail_tooltip()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Keep the overflow subtitle in step with scrolling."""
        super().watch_scroll_y(old_value, new_value)  # type: ignore[misc]
        try:
            self._refresh_rail_overflow()
        except Exception:
            pass

    def on_resize(self, _event: Resize) -> None:
        """Recompute the overflow subtitle when the viewport changes."""
        try:
            self._refresh_rail_overflow()
        except Exception:
            pass
