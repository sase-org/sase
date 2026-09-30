"""Agent list widget base: state, list updates, and in-place inserts.

This module holds the first half of the historical
``sase.ace.tui.widgets.agent_list`` implementation. The final
:class:`AgentList` subclass lives in ``_agent_list_widget`` and is
re-exported through the ``agent_list`` facade. Only public names cross
module boundaries here.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList

from ..models.agent import Agent, AgentType
from ..models.agent_groups import GroupingMode, GroupRow
from ..models.group_fold import GroupFoldView
from ._agent_list_build import build_list, try_insert_rows
from ._agent_list_rendering import AgentRenderCache
from ..util.trace import tui_trace

__all__ = ["AgentListBase"]


class AgentListBase(OptionList, inherit_bindings=False):
    """List widget showing agents."""

    # Override OptionList.BINDINGS to exclude the enter -> select binding.
    # This lets the App-level enter -> act_on_agent binding fire instead.
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
        self._unread_agents: set[tuple[AgentType, str, str | None]] = set()
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
        # All-banner map (expanded and collapsed) plus the per-row banner
        # hint and mark inputs for the paint-time rail projection.
        self._group_at_row: dict[int, GroupRow] = {}
        self._banner_hint_at_row: dict[int, str | None] = {}
        self._banner_mark_at_row: dict[int, str] = {}
        # Rail projection state: flag, last published overflow subtitle,
        # and per-Option (prompt, visual) cache. See
        # ``_agent_list_rail_mode``.
        self._rail_enabled: bool = False
        self._rail_overflow_plain: str = ""
        self._rail_visual_cache: dict[Any, tuple[Any, ...]] = {}
        self._rail_anchor_rows: dict[int, int] | None = None
        self._rail_tooltip_index: int | None = None
        # Active grouping mode for the current render.  Updated on every
        # ``update_list`` call so the test/inspection helpers
        # (``_format_banner_option``) match the most recent render.
        self._grouping_mode: GroupingMode = GroupingMode.STANDARD
        # Per-widget render cache: reuses Option/Text triples across
        # refreshes when nothing in the agent's visible state changed.
        # Phase 3 of sdd/tales/202604/instant_jk_navigation.md.
        self._agent_render_cache: AgentRenderCache = AgentRenderCache()
        self._tribe_identity_colors: dict[str, str] = {}
        # Per-row render context, populated by ``update_list`` and read by
        # ``patch_agent_row`` so a single-row update can re-emit an Option
        # with the same alignment width / mark / fold annotation it had
        # at full-rebuild time.
        self._row_render_ctx: dict[int, dict[str, Any]] = {}
        self._target_width: int = 0
        # Widest ``left`` and ``suffix`` column of the emitted agent rows.
        # ``_target_width`` is derived from them, so a row inserted in place
        # only keeps every existing row's alignment when it fits under both.
        self._max_left: int = 0
        self._max_suffix: int = 0
        # Why the last ``try_insert_rows`` declined (``None`` when it did not
        # apply); the display layer reports it as the fallback reason.
        self._insert_decline_reason: str | None = None
        self._content_requested_width: int = 0
        self._requested_width: int = 0
        self._panel_collapsed: bool = False
        # Inputs of the last panel-owner paint; ``None`` once anything else
        # repaints the rows, so a stale snapshot can never match.
        self._panel_paint_key: tuple[Any, ...] | None = None
        # Per-agent tier-guide gutter styles, captured during ``update_list``
        # so ``patch_agent_row`` can reproduce the same gutter on a single-
        # row re-render without rewalking the grouping tree.
        self._row_tier_styles: dict[int, tuple[str, ...]] = {}
        # O(1) row lookups (Phase 4 of sdd/tales/202604/tui_perf_overhaul_1.md):
        # populated alongside ``_row_entries`` during ``update_list`` so
        # ``update_highlight`` / ``_row_index_for_agent`` / ``patch_agent_row``
        # never linearly scan ``_row_entries`` to find a target row.
        self._row_by_agent_attempt: dict[tuple[int, int | None], int] = {}
        self._row_by_agent_idx: dict[int, int] = {}
        self._banner_row_by_key: dict[tuple[str, ...], int] = {}
        self._rendered_group_folds: frozenset[tuple[str, ...]] | None = None
        # Runtime-tick suffix fast path (phase runtime-tick-caches): last
        # rendered left/suffix parts keyed by agent identity so the 1 Hz tick
        # can reuse the left Text and skip rows whose suffix text is
        # unchanged without touching the full render cache.
        self._row_last_left_by_identity: dict[Any, Any] = {}
        self._row_last_suffix_plain_by_identity: dict[Any, str] = {}

    def update_list(
        self,
        agents: list[Agent],
        current_idx: int,
        fold_counts: dict[str, tuple[int, int]] | None = None,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
        fold_restore_marked_keys: Collection[str] | None = None,
        jump_hints: dict[int, str] | None = None,
        banner_jump_hints: dict[tuple[str, ...], str] | None = None,
        current_attempt_number: int | None = None,
        fold_registry: GroupFoldView | None = None,
        current_group_key: tuple[str, ...] | None = None,
        grouping_mode: GroupingMode = GroupingMode.STANDARD,
        tribe_labels: list[str | None] | None = None,
        panel_tribe: str | None = None,
        parents_with_visible_children: set[str] | None = None,
        fully_expanded_parents: set[str] | None = None,
        now: datetime | None = None,
    ) -> None:
        """Update the list with new agents.

        Args:
            agents: List of Agents to display
            current_idx: Index of currently selected agent
            fold_counts: Optional dict mapping workflow raw_suffix to
                (non_hidden_count, hidden_count) for fold annotations
            marked_agents: Optional set of marked agent identities
            unread_agents: Optional set of completed agent identities with unseen
                results in this TUI session.
            fold_restore_marked_keys: Optional fold keys whose owner rows should
                show the armed ``-`` restore preview marker.
            jump_hints: Optional row index -> adaptive hint mapping
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
                Defaults to ``STANDARD`` (project → Patch → name-root);
                ``BY_DATE`` and ``BY_STATUS`` swap L0 for a date / status
                bucket and drop the Patch layer.  Phase 2 callers
                hardcode ``STANDARD``; Phase 3 wires this to a cyclable
                app-level setting.
            tribe_labels: Optional display-only effective tribe labels aligned
                to ``agents``. Used by merged-panel mode so rows retain their
                tribe context without mutating :attr:`Agent.tribe`.
            panel_tribe: Optional tribe already communicated by the enclosing
                split panel. Clan rows omit only this matching badge; merged
                and the reserved ``@default`` panel passes ``None``.
            parents_with_visible_children: Optional global visible-parent keys
                used when a parent and child render in different tribe panels.
            fully_expanded_parents: Optional global parent keys with visible
                hidden children, paired with ``parents_with_visible_children``.
            now: Reference time for ``BY_DATE`` bucketing.  Defaults to
                ``datetime.now()``; tests pass a fixed value so bucket
                membership is deterministic.
        """
        # ``current_attempt_number`` is accepted for API compatibility with
        # the pinned-attempt detail state but no longer affects rebuild
        # output (prior-attempt child rows aren't rendered).
        del current_attempt_number
        self._panel_paint_key = None
        agents, current_idx, jump_hints, tribe_labels = self._rendered_rows(
            agents, current_idx, jump_hints, tribe_labels
        )
        with tui_trace("widget.agent_list.update_list", count=len(agents)):
            build_list(
                self,
                agents,
                current_idx,
                fold_counts=fold_counts,
                marked_agents=marked_agents,
                unread_agents=unread_agents,
                fold_restore_marked_keys=fold_restore_marked_keys,
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                fold_registry=fold_registry,
                current_group_key=current_group_key,
                grouping_mode=grouping_mode,
                tribe_labels=tribe_labels,
                panel_tribe=panel_tribe,
                parents_with_visible_children=parents_with_visible_children,
                fully_expanded_parents=fully_expanded_parents,
                now=now,
            )

    @staticmethod
    def _rendered_rows(
        agents: list[Agent],
        current_idx: int,
        jump_hints: dict[int, str] | None,
        tribe_labels: list[str | None] | None,
    ) -> tuple[list[Agent], int, dict[int, str] | None, list[str | None] | None]:
        """Drop agents without an Agents-tab row and re-index the parallel inputs."""
        from ..models.agent_panels import agent_is_rendered_in_agents_panel

        display_pairs = [
            (idx, agent)
            for idx, agent in enumerate(agents)
            if agent_is_rendered_in_agents_panel(agent)
        ]
        if len(display_pairs) == len(agents):
            return agents, current_idx, jump_hints, tribe_labels
        local_index_map = {
            source_idx: display_idx
            for display_idx, (source_idx, _agent) in enumerate(display_pairs)
        }
        if jump_hints:
            jump_hints = {
                local_index_map[source_idx]: hint
                for source_idx, hint in jump_hints.items()
                if source_idx in local_index_map
            }
        if tribe_labels is not None:
            tribe_labels = [
                tribe_labels[source_idx] if source_idx < len(tribe_labels) else None
                for source_idx, _agent in display_pairs
            ]
        return (
            [agent for _source_idx, agent in display_pairs],
            local_index_map.get(current_idx, -1),
            jump_hints,
            tribe_labels,
        )

    def try_insert_rows(
        self,
        agents: list[Agent],
        current_idx: int,
        fold_counts: dict[str, tuple[int, int]] | None = None,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
        fold_restore_marked_keys: Collection[str] | None = None,
        jump_hints: dict[int, str] | None = None,
        banner_jump_hints: dict[tuple[str, ...], str] | None = None,
        current_attempt_number: int | None = None,
        fold_registry: GroupFoldView | None = None,
        current_group_key: tuple[str, ...] | None = None,
        grouping_mode: GroupingMode = GroupingMode.STANDARD,
        tribe_labels: list[str | None] | None = None,
        panel_tribe: str | None = None,
        parents_with_visible_children: set[str] | None = None,
        fully_expanded_parents: set[str] | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Insert newly arrived rows in place instead of rebuilding the list.

        Takes the same arguments as :meth:`update_list` with ``agents`` being
        the panel's full new list. Returns ``True`` when every new row landed
        and the existing rows were left untouched; ``False`` (with the reason
        in :attr:`_insert_decline_reason`) when the caller must fall back to
        ``update_list``. See ``try_insert_rows`` in ``_agent_list_build`` for
        the gates.
        """
        del current_attempt_number
        agents, current_idx, jump_hints, tribe_labels = self._rendered_rows(
            agents, current_idx, jump_hints, tribe_labels
        )
        with tui_trace("widget.agent_list.try_insert_rows", count=len(agents)):
            return try_insert_rows(
                self,
                agents,
                current_idx,
                fold_counts=fold_counts,
                marked_agents=marked_agents,
                unread_agents=unread_agents,
                fold_restore_marked_keys=fold_restore_marked_keys,
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                fold_registry=fold_registry,
                current_group_key=current_group_key,
                grouping_mode=grouping_mode,
                tribe_labels=tribe_labels,
                panel_tribe=panel_tribe,
                parents_with_visible_children=parents_with_visible_children,
                fully_expanded_parents=fully_expanded_parents,
                now=now,
            )
