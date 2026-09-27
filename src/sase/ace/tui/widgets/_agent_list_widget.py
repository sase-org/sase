"""Agent list widget: highlight, patching, formatting, and events.

This module holds the second half of the historical
``sase.ace.tui.widgets.agent_list`` implementation. :class:`AgentList`
extends :class:`AgentListBase` (in ``_agent_list_base``) and is
re-exported through the ``agent_list`` facade. Only public names cross
module boundaries here.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import DuplicateID, Option

from ..agent_completion import WaitDependencyStatusCounts
from ..models.agent import Agent, AgentType, AttemptRecord
from ..models.agent_groups import GroupingMode, GroupRow
from ..models.agent_time import row_runtime_or_wait_ticks
from ._agent_list_base import AgentListBase
from ._agent_list_build import (
    compute_tier_styles,
    patch_row,
    resolve_row,
    try_remove_rows,
)
from ._agent_list_rail_mode import AgentListRailMixin
from ._agent_list_rendering import (
    BannerMarkState,
    assemble_padded_option,
    format_agent_option,
    format_attempt_option,
    format_banner_option,
)
from ._agent_list_styling import BANNER_ROW
from ..util.trace import tui_trace

__all__ = ["AgentList"]


class AgentList(AgentListRailMixin, AgentListBase):
    """List widget showing agents."""

    def install_options(self, options: list[Option]) -> None:
        """Swap the whole option list in one step, keeping highlight and scroll.

        Textual only appends (``add_options``) or removes (``remove_option_*``);
        it has no insert. Removing and re-adding the tail would clamp the
        highlight and scroll offset in between, and ``set_options`` resets both.
        This mirrors the bookkeeping ``add_options`` does so the list can gain
        rows mid-list atomically. Raises :class:`DuplicateID` before touching
        anything when two options share an id.
        """
        ids = [option.id for option in options if option.id is not None]
        if len(ids) != len(set(ids)):
            raise DuplicateID("Options contain duplicated IDs")
        self._options[:] = options
        self._option_to_index = {option: idx for idx, option in enumerate(options)}
        self._id_to_option = {
            option.id: option for option in options if option.id is not None
        }
        self._mouse_hovering_over = None
        self._clear_caches()
        if self.is_mounted:
            self.refresh(layout=self.styles.auto_dimensions)
            self._update_lines()

    def render_collapsed(self, *, grouping_mode: GroupingMode) -> None:
        """Render this panel as a title-only border strip.

        A collapsed panel holds no rows or banners, so it records the grouping
        mode it painted under; otherwise it would keep the ``STANDARD`` default
        and make the app-wide grouping-mode guard force a full rebuild.
        """
        self._programmatic_update = True
        try:
            self.clear_options()
            self._agents = []
            self._unread_agents = set()
            self._tribe_identity_colors = {}
            self._row_entries = []
            self._banner_at_row = {}
            self._group_at_row = {}
            self._banner_hint_at_row = {}
            self._banner_mark_at_row = {}
            self._row_render_ctx = {}
            self._row_tier_styles = {}
            self._row_by_agent_attempt = {}
            self._row_by_agent_idx = {}
            self._banner_row_by_key = {}
            self._rendered_group_folds = None
            self._target_width = 0
            self._max_left = 0
            self._max_suffix = 0
            self._content_requested_width = 0
            self._panel_collapsed = True
            self._grouping_mode = grouping_mode
            self._panel_paint_key = None
            self._refresh_requested_width()
        finally:
            self._programmatic_update = False
        self._rail_rows_changed()

    def update_border_title(self, title: Text | str) -> None:
        """Set the panel title and include it in dynamic width negotiation."""
        self.border_title = title
        self._refresh_requested_width()

    def _refresh_requested_width(self) -> None:
        """Publish the larger of the rendered-content and border-title widths."""
        title = self.border_title
        title_width = (
            title.cell_len
            if isinstance(title, Text)
            else Text.from_markup(str(title or "")).cell_len
        )
        requested_width = max(self._content_requested_width, title_width + 4)
        if requested_width == self._requested_width:
            return
        self._requested_width = requested_width
        self.post_message(self.WidthChanged(requested_width))

    def _compute_tier_styles(
        self,
        tree: list,
        *,
        panel_uses_cs: bool,
    ) -> tuple[dict[int, tuple[str, ...]], list[tuple[str, ...]]]:
        """Backwards-compatible shim around :func:`compute_tier_styles`."""
        return compute_tier_styles(tree, panel_uses_cs=panel_uses_cs)

    def update_highlight(
        self,
        current_idx: int,
        current_attempt_number: int | None = None,
        group_key: tuple[str, ...] | None = None,
    ) -> None:
        """Move the highlight without clearing/rebuilding options.

        Use this for j/k navigation where the agent list hasn't changed,
        only the selection index.

        Args:
            current_idx: Agent index to highlight.
            current_attempt_number: Accepted for compatibility with pinned
                attempt detail state. Falls back to the selected agent row when
                no matching attempt row exists.
            group_key: When non-None, highlight the banner row whose
                ``GroupRow.group_key`` matches.  Falls back to the agent-row
                search when no banner matches (defensive against
                refresh-vs-fold races).
        """
        with tui_trace("widget.agent_list.update_highlight", count=len(self._agents)):
            if group_key is not None:
                row = self._banner_row_by_key.get(group_key)
                if row is not None:
                    self._set_highlighted_programmatically(row)
                    return
            if not self._agents or not (0 <= current_idx < len(self._agents)):
                return
            row = self._row_by_agent_attempt.get((current_idx, current_attempt_number))
            if row is None and current_attempt_number is not None:
                row = self._row_by_agent_idx.get(current_idx)
            if row is not None:
                self._set_highlighted_programmatically(row)

    def _set_highlighted_programmatically(self, row: int) -> None:
        """Assign highlight silently while still keeping the row visible."""
        self._programmatic_update = True
        try:
            self.highlighted = row
            self.scroll_to_highlight()
        finally:
            self._programmatic_update = False

    def clear_highlight(self) -> None:
        """Clear highlight silently without moving the scroll viewport."""
        self._programmatic_update = True
        try:
            self.highlighted = None
        finally:
            self._programmatic_update = False

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

    def watch_highlighted(self, highlighted: int | None) -> None:
        """Suppress OptionHighlighted messages during programmatic updates.

        Without this override the parent ``OptionList.watch_highlighted``
        posts an ``OptionHighlighted`` message every time ``self.highlighted``
        is reassigned. During a programmatic rebuild that message would
        race with the deferred flag-clear and end up at
        ``on_option_list_option_highlighted`` after ``_programmatic_update``
        had already been reset to ``False`` — producing a phantom
        ``SelectionChanged`` that overwrote ``current_idx`` with row 0.
        Synchronously short-circuiting the watch keeps the rebuild silent.
        """
        from ..util.trace import trace_event

        if self._programmatic_update:
            trace_event(
                "widget.agent_list.watch_highlighted.suppressed",
                highlighted=highlighted,
            )
            return
        trace_event(
            "widget.agent_list.watch_highlighted",
            highlighted=highlighted,
        )
        super().watch_highlighted(highlighted)

    # ------------------------------------------------------------------
    # Selective single-row patching (Phase 3 of instant_jk_navigation)
    # ------------------------------------------------------------------

    def _row_index_for_agent(self, agent_idx: int) -> int | None:
        """Locate the OptionList row index showing ``agents[agent_idx]``.

        Returns ``None`` when no row maps to that agent (e.g. it lives in
        another panel, or the index is stale).
        """
        return self._row_by_agent_idx.get(agent_idx)

    def visible_agents(self) -> list[Agent]:
        """Return agents represented by currently rendered rows.

        Banner rows are skipped and duplicate agent rows are de-duped while
        preserving on-screen order.
        """
        visible: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        for agent_idx, _attempt_number in self._row_entries:
            if agent_idx == BANNER_ROW:
                continue
            if not (0 <= agent_idx < len(self._agents)):
                continue
            agent = self._agents[agent_idx]
            if agent.identity in seen:
                continue
            seen.add(agent.identity)
            visible.append(agent)
        return visible

    def try_remove_rows(
        self,
        removed_identities: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Apply optimistic removes in place when conservative gates hold.

        Returns ``True`` when every removal landed; ``False`` when the
        caller must fall back to a full ``update_list`` rebuild. Banner
        chip counts may briefly drift on the fast path until the next
        full refresh — see ``try_remove_rows`` in ``_agent_list_build``.
        """
        with tui_trace(
            "widget.agent_list.try_remove_rows", count=len(removed_identities)
        ):
            return try_remove_rows(self, removed_identities)

    def patch_agent_row(
        self,
        agent_idx: int,
        *,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
        is_selected: bool | None = None,
        now: datetime | None = None,
        wait_dependency_counts: WaitDependencyStatusCounts | None = None,
    ) -> bool:
        """Replace one agent's Option in place when nothing structural changed.

        Returns ``True`` when the patch landed; ``False`` when the caller
        must fall back to a full ``update_list`` rebuild (e.g. the agent
        isn't in this panel, the alignment width grew past the cached
        target, or the per-row context wasn't captured by a previous full
        render).
        """
        with tui_trace("widget.agent_list.patch_agent_row", agent_idx=agent_idx):
            return patch_row(
                self,
                agent_idx,
                marked_agents=marked_agents,
                unread_agents=unread_agents,
                is_selected=is_selected,
                now=now,
                wait_dependency_counts=wait_dependency_counts,
            )

    def patch_active_runtime_rows(self, now: datetime) -> int:
        """Patch visible rows whose compact time text advances with time.

        This is a cosmetic clock-tick path: failed row patches are ignored
        because the next normal agent refresh will rebuild stale rows.
        """
        patched = 0
        for local_idx, agent in enumerate(self._agents):
            if not self._runtime_suffix_ticks(agent):
                continue
            if self.patch_agent_row(local_idx, now=now):
                patched += 1
        return patched

    @staticmethod
    def _runtime_suffix_ticks(agent: Agent) -> bool:
        """Return True when *agent* renders time text that can change each tick."""
        return row_runtime_or_wait_ticks(agent)

    def _format_agent_option(
        self,
        agent: Agent,
        index: int,
        is_selected: bool,
        fold_annotation: str = "",
        is_expanded: bool = False,
        is_marked: bool = False,
        is_unread: bool = False,
        hint_char: str | None = None,
    ) -> Option:
        """Format an agent as an option for display (single-row, no alignment)."""
        left, suffix, option_id = format_agent_option(
            agent,
            index,
            is_selected=is_selected,
            fold_annotation=fold_annotation,
            is_expanded=is_expanded,
            is_marked=is_marked,
            is_unread=is_unread,
            hint_char=hint_char,
        )
        natural_width = left.cell_len + (2 if suffix.cell_len else 0) + suffix.cell_len
        return assemble_padded_option(
            left, suffix, width=natural_width, option_id=option_id
        )

    def _format_banner_option(
        self,
        group: GroupRow,
        *,
        width: int,
        sequence: int,
        selectable: bool = False,
        mark_state: BannerMarkState = "none",
    ) -> Option:
        """Render a group banner row Option."""
        return format_banner_option(
            group,
            self._agents,
            width=width,
            sequence=sequence,
            selectable=selectable,
            mode=self._grouping_mode,
            mark_state=mark_state,
        )

    def _format_attempt_option(
        self,
        agent: Agent,
        record: AttemptRecord,
        *,
        is_selected: bool,
    ) -> Option:
        """Format a prior-attempt row as a selectable child of ``agent``."""
        left, suffix, option_id = format_attempt_option(
            agent, record, is_selected=is_selected
        )
        natural_width = left.cell_len + (2 if suffix.cell_len else 0) + suffix.cell_len
        return assemble_padded_option(
            left, suffix, width=natural_width, option_id=option_id
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Handle option highlight (keyboard navigation)."""
        # Only post message for user-initiated navigation, not programmatic updates
        if event.option_index is not None and not self._programmatic_update:
            agent_idx, attempt_number, group_key = self._resolve_row(event.option_index)
            self.post_message(
                self.SelectionChanged(
                    agent_idx,
                    attempt_number=attempt_number,
                    group_key=group_key,
                )
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if event.option_index is not None:
            agent_idx, attempt_number, group_key = self._resolve_row(event.option_index)
            self.post_message(
                self.SelectionChanged(
                    agent_idx,
                    attempt_number=attempt_number,
                    group_key=group_key,
                )
            )

    def _resolve_row(
        self, option_index: int
    ) -> tuple[int, int | None, tuple[str, ...] | None]:
        """Translate a raw OptionList row index to selection state.

        Returns ``(agent_idx, attempt_number, group_key)``.  When a
        selectable (collapsed) banner row is hit the ``group_key`` is the
        banner's :attr:`GroupRow.group_key` and ``agent_idx`` points at
        the first agent in the group so the detail panel still has
        something to show.  When a banner is non-selectable (its group
        is expanded) the row resolves to the next agent row.
        """
        return resolve_row(option_index, self._row_entries, self._banner_at_row)
