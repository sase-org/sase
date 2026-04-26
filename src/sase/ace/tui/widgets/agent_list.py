"""Agent list widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType, AttemptRecord
from ..models.agent_groups import (
    GroupRow,
    TreeEntry,
    build_agent_tree,
)
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    assemble_padded_option,
    format_agent_option,
    format_attempt_option,
    format_banner_option,
)
from ._agent_list_styling import (
    _BANNER_ROW,
    _MIN_BANNER_WIDTH,
)

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
        is non-None when a prior-attempt child row is selected (the detail view
        should then pin to that attempt rather than the agent's live state).
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
        # attempt_number is None for an agent row, int for an attempt child.
        self._row_entries: list[tuple[int, int | None]] = []
        # Sparse map row_index -> GroupRow for selectable banners (group fold
        # level < 2).  Banner rows at fold level 2 stay disabled and skip the
        # map entirely so they remain invisible to selection.
        self._banner_at_row: dict[int, GroupRow] = {}

    def update_list(
        self,
        agents: list[Agent],
        current_idx: int,
        fold_counts: dict[str, tuple[int, int]] | None = None,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        jump_hints: dict[int, str] | None = None,
        current_attempt_number: int | None = None,
        group_fold_level: int = 2,
        current_group_key: tuple[str, ...] | None = None,
    ) -> None:
        """Update the list with new agents.

        Args:
            agents: List of Agents to display
            current_idx: Index of currently selected agent
            fold_counts: Optional dict mapping workflow raw_suffix to
                (non_hidden_count, hidden_count) for fold annotations
            marked_agents: Optional set of marked agent identities
            jump_hints: Optional row index -> hint character mapping
            current_attempt_number: When non-None, highlight the corresponding
                attempt child row of the selected agent instead of the agent row.
            group_fold_level: Global group-fold level (0–2).  At ``2`` (default)
                every banner and agent row is shown and banners are
                non-selectable.  At lower levels only banners up to that level
                appear, agents are hidden, and banners become selectable.
            current_group_key: When non-None, highlight the banner row whose
                ``group_key`` matches.  Takes precedence over agent highlight.
        """
        self._programmatic_update = True
        self._agents = agents
        self.clear_options()
        self._row_entries = []
        self._banner_at_row = {}

        marked = marked_agents or set()

        # Determine which parents have visible children in the filtered list
        parents_with_visible_children: set[str] = set()
        fully_expanded_parents: set[str] = set()
        for agent in agents:
            if agent.is_workflow_child and agent.parent_timestamp:
                parents_with_visible_children.add(agent.parent_timestamp)
                if agent.is_hidden_step:
                    fully_expanded_parents.add(agent.parent_timestamp)

        # Pre-format agent and attempt rows so we know their widths before
        # emitting banner rules (banners are stretched to the widest row,
        # and the runtime suffix is right-aligned to the same column).
        agent_parts: dict[int, tuple[Any, Any, str]] = {}
        attempt_parts: dict[tuple[int, int], tuple[Any, Any, str]] = {}
        max_left = 0
        max_suffix = 0
        for i, agent in enumerate(agents):
            is_expanded = (
                agent.raw_suffix is not None
                and agent.raw_suffix in parents_with_visible_children
            )
            is_marked = agent.identity in marked
            annotation = compute_fold_annotation(
                agent,
                fold_counts,
                parents_with_visible_children,
                fully_expanded_parents,
            )
            is_selected_agent = i == current_idx and current_attempt_number is None
            left, suffix, option_id = format_agent_option(
                agent,
                i,
                is_selected=is_selected_agent,
                fold_annotation=annotation,
                is_expanded=is_expanded,
                is_marked=is_marked,
                hint_char=(jump_hints or {}).get(i),
            )
            agent_parts[i] = (left, suffix, option_id)
            max_left = max(max_left, left.cell_len)
            max_suffix = max(max_suffix, suffix.cell_len)
            if not agent.is_workflow_child:
                for record in agent.attempt_history:
                    is_selected_attempt = (
                        i == current_idx
                        and current_attempt_number == record.attempt_number
                    )
                    a_left, a_suffix, a_id = format_attempt_option(
                        agent,
                        record,
                        is_selected=is_selected_attempt,
                    )
                    attempt_parts[(i, record.attempt_number)] = (a_left, a_suffix, a_id)
                    max_left = max(max_left, a_left.cell_len)
                    max_suffix = max(max_suffix, a_suffix.cell_len)

        gap = 2 if max_suffix > 0 else 0
        target_width = max(_MIN_BANNER_WIDTH, max_left + gap + max_suffix)
        banner_width = target_width

        agent_options: dict[int, Option] = {
            i: assemble_padded_option(
                left, suffix, width=target_width, option_id=option_id
            )
            for i, (left, suffix, option_id) in agent_parts.items()
        }
        attempt_options: dict[tuple[int, int], Option] = {
            key: assemble_padded_option(
                left, suffix, width=target_width, option_id=option_id
            )
            for key, (left, suffix, option_id) in attempt_parts.items()
        }
        max_width = target_width

        # Walk the grouping tree and emit Options in display order.
        effective_level = group_fold_level
        tree: list[TreeEntry] = build_agent_tree(
            agents, group_fold_level=effective_level
        )

        # Banners are selectable whenever the group fold has hidden the level
        # below them.  At fold level 2 (full expansion) every banner stays
        # disabled so cursor navigation skips them and lands on agents.
        banners_selectable = effective_level < 2

        highlighted_row: int | None = None
        banner_seq = 0
        spacer_seq = 0
        seen_first_l0 = False
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.level == 0:
                    if seen_first_l0:
                        # Insert a blank spacer row before each non-first
                        # L0 banner so adjacent project groups don't read
                        # as one continuous block.  Disabled so cursor
                        # navigation skips it.
                        spacer = Option(
                            Text(""),
                            id=f"spacer:{spacer_seq}",
                            disabled=True,
                        )
                        spacer_seq += 1
                        self.add_option(spacer)
                        self._row_entries.append((_BANNER_ROW, None))
                    seen_first_l0 = True
                option = format_banner_option(
                    entry.group,
                    self._agents,
                    width=banner_width,
                    sequence=banner_seq,
                    selectable=banners_selectable,
                )
                banner_seq += 1
                row_index = len(self._row_entries)
                self.add_option(option)
                self._row_entries.append((_BANNER_ROW, None))
                if banners_selectable:
                    self._banner_at_row[row_index] = entry.group
                    if (
                        current_group_key is not None
                        and entry.group.group_key == current_group_key
                        and highlighted_row is None
                    ):
                        highlighted_row = row_index
                continue

            if entry.agent_idx is None:
                continue
            i = entry.agent_idx
            agent = agents[i]
            option = agent_options[i]
            self.add_option(option)
            is_selected_agent = (
                current_group_key is None
                and i == current_idx
                and current_attempt_number is None
            )
            if is_selected_agent:
                highlighted_row = len(self._row_entries)
            self._row_entries.append((i, None))

            if agent.is_workflow_child:
                continue
            for record in agent.attempt_history:
                attempt_option = attempt_options[(i, record.attempt_number)]
                self.add_option(attempt_option)
                is_selected_attempt = (
                    current_group_key is None
                    and i == current_idx
                    and current_attempt_number == record.attempt_number
                )
                if is_selected_attempt:
                    highlighted_row = len(self._row_entries)
                self._row_entries.append((i, record.attempt_number))

        # Add padding for border, scrollbar, visual comfort (~8 cells)
        _PADDING = 8
        optimal_width = max(max_width, banner_width) + _PADDING
        self.post_message(self.WidthChanged(optimal_width))

        if highlighted_row is not None:
            self.highlighted = highlighted_row

        # Clear flag after event loop processes pending events
        self.call_later(self._clear_programmatic_flag)

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
            current_attempt_number: When non-None, highlight the attempt child
                row of ``current_idx`` instead of the agent row.
            group_key: When non-None, highlight the banner row whose
                ``GroupRow.group_key`` matches.  Falls back to the agent-row
                search when no banner matches (defensive against
                refresh-vs-fold races).
        """
        if group_key is not None:
            for row, banner in self._banner_at_row.items():
                if banner.group_key == group_key:
                    self._programmatic_update = True
                    self.highlighted = row
                    self.call_later(self._clear_programmatic_flag)
                    return
        if not self._agents or not (0 <= current_idx < len(self._agents)):
            return
        target = (current_idx, current_attempt_number)
        for row, entry in enumerate(self._row_entries):
            if entry == target:
                self._programmatic_update = True
                self.highlighted = row
                self.call_later(self._clear_programmatic_flag)
                return

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

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
        selectable banner row is hit (group fold level < 2) the
        ``group_key`` is the banner's :attr:`GroupRow.group_key` and
        ``agent_idx`` points at the first agent in the group so
        the detail panel still has something to show.  When a banner is
        non-selectable (group fold level == 2) the row resolves to the
        next agent row.
        """
        if 0 <= option_index < len(self._row_entries):
            entry = self._row_entries[option_index]
            banner = self._banner_at_row.get(option_index)
            if banner is not None:
                first = banner.agent_indices[0] if banner.agent_indices else 0
                return (first, None, banner.group_key)
            if entry[0] == _BANNER_ROW:
                # Non-selectable banner — route through to a real agent row.
                for j in range(option_index + 1, len(self._row_entries)):
                    nxt = self._row_entries[j]
                    if nxt[0] != _BANNER_ROW:
                        return (nxt[0], nxt[1], None)
                for j in range(option_index - 1, -1, -1):
                    prv = self._row_entries[j]
                    if prv[0] != _BANNER_ROW:
                        return (prv[0], prv[1], None)
                return (0, None, None)
            return (entry[0], entry[1], None)
        return (option_index, None, None)
