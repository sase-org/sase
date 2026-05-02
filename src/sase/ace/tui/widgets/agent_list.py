"""Agent list widget for the ace TUI."""

from datetime import datetime
from typing import Any

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType, AttemptRecord
from ..models.agent_group_fold import AgentGroupFoldRegistry
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
)
from ._agent_list_build import (
    build_list,
    compute_tier_styles,
    patch_row,
    resolve_row,
    try_remove_rows,
)
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    AgentRenderCache,
    assemble_padded_option,
    format_agent_option,
    format_attempt_option,
    format_banner_option,
)
from ._agent_list_styling import _BANNER_ROW
from ..util.trace import tui_trace

# Re-exported under its historical name for tests that import from
# ``sase.ace.tui.widgets.agent_list``.
_compute_fold_annotation = compute_fold_annotation

__all__ = [
    "AgentList",
    "_BANNER_ROW",
    "_compute_fold_annotation",
]


class AgentList(OptionList, inherit_bindings=False):
    """List widget showing agents."""

    # Override OptionList.BINDINGS to exclude the enter -> select binding.
    # This lets the App-level enter -> jump_to_agent_changespec binding fire instead.
    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("home", "first", "First", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    class SelectionChanged(Message):
        """Message sent when selection changes.

        ``index`` is the agent index of the target agent; ``attempt_number``
        is preserved for compatibility with older attempt-row selection
        state, but the list no longer renders prior-attempt child rows.
        ``group_key`` is non-None when a banner row is the selection target —
        the index then points at the first agent in that group, but the
        ``current_group_key`` state should be updated so banner-aware actions
        (e.g. Phase 5's bulk ``x``) can target the group rather than that
        single agent.
        """

        def __init__(
            self,
            index: int,
            attempt_number: int | None = None,
            group_key: tuple[str, ...] | None = None,
        ) -> None:
            self.index = index
            self.attempt_number = attempt_number
            self.group_key = group_key
            super().__init__()

    class WidthChanged(Message):
        """Message sent when optimal width changes."""

        def __init__(self, width: int) -> None:
            self.width = width
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent list."""
        super().__init__(**kwargs)
        self._agents: list[Agent] = []
        self._programmatic_update: bool = False
        # Each rendered Option maps back to (agent_idx, attempt_number).
        # Attempt child rows are no longer emitted, so attempt_number is
        # currently None for agent rows; the tuple shape is preserved for
        # compatibility with selection/detail state.
        self._row_entries: list[tuple[int, int | None]] = []
        # Sparse map row_index -> GroupRow for selectable (collapsed) banners.
        # Expanded banners stay disabled and skip the map entirely so they
        # remain invisible to selection.
        self._banner_at_row: dict[int, GroupRow] = {}
        # Active grouping mode for the current render.  Updated on every
        # ``update_list`` call so the test/inspection helpers
        # (``_format_banner_option``) match the most recent render.
        self._grouping_mode: GroupingMode = GroupingMode.STANDARD
        # Per-widget render cache: reuses Option/Text triples across
        # refreshes when nothing in the agent's visible state changed.
        # Phase 3 of sdd/plans/202604/instant_jk_navigation.md.
        self._agent_render_cache: AgentRenderCache = AgentRenderCache()
        # Per-row render context, populated by ``update_list`` and read by
        # ``patch_agent_row`` so a single-row update can re-emit an Option
        # with the same alignment width / mark / fold annotation it had
        # at full-rebuild time.
        self._row_render_ctx: dict[int, dict[str, Any]] = {}
        self._target_width: int = 0
        # Per-agent tier-guide gutter styles, captured during ``update_list``
        # so ``patch_agent_row`` can reproduce the same gutter on a single-
        # row re-render without rewalking the grouping tree.
        self._row_tier_styles: dict[int, tuple[str, ...]] = {}
        # O(1) row lookups (Phase 4 of sdd/plans/202604/tui_perf_overhaul_1.md):
        # populated alongside ``_row_entries`` during ``update_list`` so
        # ``update_highlight`` / ``_row_index_for_agent`` / ``patch_agent_row``
        # never linearly scan ``_row_entries`` to find a target row.
        self._row_by_agent_attempt: dict[tuple[int, int | None], int] = {}
        self._row_by_agent_idx: dict[int, int] = {}
        self._banner_row_by_key: dict[tuple[str, ...], int] = {}

    def update_list(
        self,
        agents: list[Agent],
        current_idx: int,
        fold_counts: dict[str, tuple[int, int]] | None = None,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        jump_hints: dict[int, str] | None = None,
        banner_jump_hints: dict[tuple[str, ...], str] | None = None,
        current_attempt_number: int | None = None,
        fold_registry: AgentGroupFoldRegistry | None = None,
        current_group_key: tuple[str, ...] | None = None,
        grouping_mode: GroupingMode = GroupingMode.STANDARD,
        now: datetime | None = None,
    ) -> None:
        """Update the list with new agents.

        Args:
            agents: List of Agents to display
            current_idx: Index of currently selected agent
            fold_counts: Optional dict mapping workflow raw_suffix to
                (non_hidden_count, hidden_count) for fold annotations
            marked_agents: Optional set of marked agent identities
            jump_hints: Optional row index -> hint character mapping
            current_attempt_number: Accepted for compatibility with pinned
                attempt detail state. The list still highlights the selected
                agent row because prior-attempt child rows are not rendered.
            fold_registry: Per-group collapse registry.  The tree builder uses
                it to mark banner rows ``is_collapsed``; collapsed banners
                become selectable, expanded banners stay disabled so cursor
                navigation flies through agents.
            current_group_key: When non-None, highlight the banner row whose
                ``group_key`` matches.  Takes precedence over agent highlight.
            grouping_mode: Which grouping/sorting mode the tree should use.
                Defaults to ``STANDARD`` (project → ChangeSpec → name-root);
                ``BY_DATE`` and ``BY_STATUS`` swap L0 for a date / status
                bucket and drop the ChangeSpec layer.  Phase 2 callers
                hardcode ``STANDARD``; Phase 3 wires this to a cyclable
                app-level setting.
            now: Reference time for ``BY_DATE`` bucketing.  Defaults to
                ``datetime.now()``; tests pass a fixed value so bucket
                membership is deterministic.
        """
        # ``current_attempt_number`` is accepted for API compatibility with
        # the pinned-attempt detail state but no longer affects rebuild
        # output (prior-attempt child rows aren't rendered).
        del current_attempt_number
        with tui_trace("widget.agent_list.update_list", count=len(agents)):
            build_list(
                self,
                agents,
                current_idx,
                fold_counts=fold_counts,
                marked_agents=marked_agents,
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                fold_registry=fold_registry,
                current_group_key=current_group_key,
                grouping_mode=grouping_mode,
                now=now,
            )

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
                    self._programmatic_update = True
                    try:
                        self.highlighted = row
                    finally:
                        self._programmatic_update = False
                    return
            if not self._agents or not (0 <= current_idx < len(self._agents)):
                return
            row = self._row_by_agent_attempt.get((current_idx, current_attempt_number))
            if row is None and current_attempt_number is not None:
                row = self._row_by_agent_idx.get(current_idx)
            if row is not None:
                self._programmatic_update = True
                try:
                    self.highlighted = row
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
        is_selected: bool | None = None,
        now: datetime | None = None,
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
                is_selected=is_selected,
                now=now,
            )

    def _format_agent_option(
        self,
        agent: Agent,
        index: int,
        is_selected: bool,
        fold_annotation: str = "",
        is_expanded: bool = False,
        is_marked: bool = False,
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
    ) -> Option:
        """Render a group banner row Option."""
        return format_banner_option(
            group,
            self._agents,
            width=width,
            sequence=sequence,
            selectable=selectable,
            mode=self._grouping_mode,
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
