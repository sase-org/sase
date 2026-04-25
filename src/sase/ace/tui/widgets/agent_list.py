"""Agent list widget for the ace TUI."""

from typing import Any, Literal

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from sase.xprompt.workflow_output import get_substep_suffix

from ..models.agent import Agent, AgentType, AttemptRecord, format_compact_duration
from ..models.agent_groups import (
    GroupRow,
    TreeEntry,
    banner_label,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
)

# Sentinel agent_idx in ``_row_entries`` for banner (group) rows.
_BANNER_ROW = -1

# Minimum width for group banner rules.
_MIN_BANNER_WIDTH = 40

# Banner styles per level (rule + accent color).
_TAG_BANNER_STYLE = "bold #FFAF00"
_PROJECT_BANNER_STYLE = "bold #5FAFFF"
_NAME_ROOT_BANNER_STYLE = "dim #AFAFAF"

# Panel identity type
PanelId = Literal["main", "pinned"]

# Color mapping for agent types
_AGENT_TYPE_COLORS: dict[AgentType, str] = {
    AgentType.RUNNING: "#87AFFF",  # Blue
    AgentType.WORKFLOW: "#FF87D7",  # Pink for workflow agent steps
}

# Per-step-type colors for workflow child entries
_STEP_TYPE_COLORS: dict[str, str] = {
    "agent": "#5FD7FF",  # Bright cyan — LLM agent steps stand out
    "bash": "#FFAF5F",  # Warm amber — shell commands
    "python": "#87D787",  # Soft green — code execution
    "parallel": "#D7AFFF",  # Soft lavender — parallel orchestration
}

# Icon for autonomous (%approve) agents
_APPROVE_ICON = "⚡"

# Icon for pinned agents (protected from dismiss-all)
_PIN_ICON = "\U0001f4cc"  # 📌

# Icon for dismissible (completed) agents
_DONE_ICON = "✘"
_DISMISSIBLE_STATUSES = (
    "DONE",
    "FAILED",
    "PLAN DONE",
    "EPIC CREATED",
)

# Icon for hidden agents (shown when visibility is toggled on)
_HIDDEN_ICON = "◌"

# Indentation prefix for workflow child agents
_CHILD_INDENT = "  └─ "


def _short_model_name(model: str) -> str:
    """Extract short display name from a model string."""
    model_lower = model.lower()
    for keyword in ("flash", "opus", "sonnet", "haiku", "pro"):
        if keyword in model_lower:
            return keyword
    # Fallback: last segment before any date suffix
    parts = model.split("-")
    return parts[0] if parts else model


def _step_role_suffix(agent: Agent) -> str:
    """Return role suffix to include in step number, or empty string.

    Shows role_suffix (e.g., ".plan", ".code", ".q") as part of the step number
    only for agent-type workflow steps and follow-up agents.  Other step types
    (bash, python) and workflow parents do not display it.
    """
    if not agent.role_suffix:
        return ""
    # Follow-up agent (has parent_timestamp, no parent_workflow)
    if not agent.parent_workflow:
        return agent.role_suffix
    # Agent-type step within a workflow
    if agent.step_type == "agent":
        return agent.role_suffix
    return ""


def _is_foldable_parent(agent: Agent) -> bool:
    """Check if an agent is a foldable parent (workflow).

    Args:
        agent: The agent to check.

    Returns:
        True if this agent is a parent that can be folded.
    """
    if agent.is_workflow_child:
        return False
    if agent.agent_type == AgentType.WORKFLOW:
        return True
    return False


class AgentList(OptionList, inherit_bindings=False):
    """List widget showing agents, used for both main and pinned panels."""

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

        ``index`` is the local-panel index of the target agent; ``attempt_number``
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
            panel: PanelId = "main",
            attempt_number: int | None = None,
            group_key: tuple[str, ...] | None = None,
        ) -> None:
            self.index = index
            self.panel = panel
            self.attempt_number = attempt_number
            self.group_key = group_key
            super().__init__()

    class WidthChanged(Message):
        """Message sent when optimal width changes."""

        def __init__(self, width: int, panel: PanelId = "main") -> None:
            self.width = width
            self.panel = panel
            super().__init__()

    def __init__(self, panel: PanelId = "main", **kwargs: Any) -> None:
        """Initialize the agent list.

        Args:
            panel: Which panel this list belongs to ("main" or "pinned").
        """
        super().__init__(**kwargs)
        self._agents: list[Agent] = []
        self._programmatic_update: bool = False
        self._panel: PanelId = panel
        # Each rendered Option maps back to (agent_local_idx, attempt_number).
        # attempt_number is None for an agent row, int for an attempt child.
        self._row_entries: list[tuple[int, int | None]] = []
        # Sparse map row_index -> GroupRow for selectable banners (group fold
        # level < 3).  Banner rows at fold level 3 stay disabled and skip the
        # map entirely so they remain invisible to selection.
        self._banner_at_row: dict[int, GroupRow] = {}

    def update_list(
        self,
        agents: list[Agent],
        current_idx: int,
        fold_counts: dict[str, tuple[int, int]] | None = None,
        pinned_agents: set[tuple[AgentType, str, str | None]] | None = None,
        marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
        has_focus: bool = True,
        jump_hints: dict[int, str] | None = None,
        current_attempt_number: int | None = None,
        group_fold_level: int = 3,
        current_group_key: tuple[str, ...] | None = None,
    ) -> None:
        """Update the list with new agents.

        Args:
            agents: List of Agents to display
            current_idx: Index of currently selected agent
            fold_counts: Optional dict mapping workflow raw_suffix to
                (non_hidden_count, hidden_count) for fold annotations
            pinned_agents: Optional set of pinned agent identities
            marked_agents: Optional set of marked agent identities
            has_focus: Whether this panel currently has focus
            jump_hints: Optional local row index -> hint character mapping
            current_attempt_number: When non-None, highlight the corresponding
                attempt child row of the selected agent instead of the agent row.
            group_fold_level: Global group-fold level (0–3).  At ``3`` (default)
                every banner and agent row is shown and banners are
                non-selectable.  At lower levels only banners up to that level
                appear, agents are hidden, and banners become selectable.
                Always ``3`` for the pinned panel (the panel stays flat).
            current_group_key: When non-None, highlight the banner row whose
                ``group_key`` matches.  Takes precedence over agent highlight.
        """
        self._programmatic_update = True
        self._agents = agents
        self.clear_options()
        self._row_entries = []
        self._banner_at_row = {}

        pinned = pinned_agents or set()
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
        # emitting banner rules (banners are stretched to the widest row).
        # Pinned panel stays flat in Phase 3 and skips banners entirely.
        agent_options: dict[int, Option] = {}
        attempt_options: dict[tuple[int, int], Option] = {}
        max_width = 0
        for i, agent in enumerate(agents):
            is_expanded = (
                agent.raw_suffix is not None
                and agent.raw_suffix in parents_with_visible_children
            )
            is_pinned = agent.identity in pinned
            is_marked = agent.identity in marked
            annotation = _compute_fold_annotation(
                agent,
                fold_counts,
                parents_with_visible_children,
                fully_expanded_parents,
            )
            is_selected_agent = (
                has_focus and i == current_idx and current_attempt_number is None
            )
            option = self._format_agent_option(
                agent,
                i,
                is_selected=is_selected_agent,
                fold_annotation=annotation,
                is_expanded=is_expanded,
                is_pinned=is_pinned,
                is_marked=is_marked,
                hint_char=(jump_hints or {}).get(i),
            )
            agent_options[i] = option
            max_width = max(max_width, option.prompt.cell_len)  # type: ignore[union-attr]
            if not agent.is_workflow_child:
                for record in agent.attempt_history:
                    is_selected_attempt = (
                        has_focus
                        and i == current_idx
                        and current_attempt_number == record.attempt_number
                    )
                    attempt_option = self._format_attempt_option(
                        agent,
                        record,
                        is_selected=is_selected_attempt,
                    )
                    attempt_options[(i, record.attempt_number)] = attempt_option
                    max_width = max(
                        max_width,
                        attempt_option.prompt.cell_len,  # type: ignore[union-attr]
                    )

        banner_width = max(_MIN_BANNER_WIDTH, max_width)

        # Walk the grouping tree (main panel) or the flat agent list
        # (pinned panel) and emit Options in display order.  The pinned
        # panel stays flat regardless of group_fold_level.
        if self._panel == "main":
            effective_level = group_fold_level
            tree = build_agent_tree(agents, group_fold_level=effective_level)
        else:
            effective_level = 3
            tree = [TreeEntry(kind="agent", agent_idx=i) for i in range(len(agents))]

        # Banners are selectable on the main panel whenever the group
        # fold has hidden the level below them.  At fold level 3 (full
        # expansion) every banner stays disabled so cursor navigation
        # skips them and lands on agents — preserving Phase 3 behavior.
        banners_selectable = self._panel == "main" and effective_level < 3

        highlighted_row: int | None = None
        banner_seq = 0
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                option = self._format_banner_option(
                    entry.group,
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
                        has_focus
                        and current_group_key is not None
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
                has_focus
                and current_group_key is None
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
                    has_focus
                    and current_group_key is None
                    and i == current_idx
                    and current_attempt_number == record.attempt_number
                )
                if is_selected_attempt:
                    highlighted_row = len(self._row_entries)
                self._row_entries.append((i, record.attempt_number))

        # Add padding for border, scrollbar, visual comfort (~8 cells)
        _PADDING = 8
        optimal_width = max(max_width, banner_width) + _PADDING
        self.post_message(self.WidthChanged(optimal_width, panel=self._panel))

        # Highlight the current item only if this panel has focus
        if has_focus and highlighted_row is not None:
            self.highlighted = highlighted_row
        elif not has_focus:
            self.highlighted = None

        # Clear flag after event loop processes pending events
        self.call_later(self._clear_programmatic_flag)

    def update_highlight(
        self, current_idx: int, current_attempt_number: int | None = None
    ) -> None:
        """Move the highlight without clearing/rebuilding options.

        Use this for j/k navigation where the agent list hasn't changed,
        only the selection index.

        Args:
            current_idx: Agent local index to highlight.
            current_attempt_number: When non-None, highlight the attempt child
                row of ``current_idx`` instead of the agent row.
        """
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
        is_pinned: bool = False,
        is_marked: bool = False,
        hint_char: str | None = None,
    ) -> Option:
        """Format an agent as an option for display.

        Args:
            agent: The Agent to format
            index: Index of the agent in the list
            is_selected: Whether this is the currently selected item
            fold_annotation: Fold annotation text to append
            is_expanded: Whether this agent's fold state is expanded
            is_pinned: Whether this agent is pinned
            is_marked: Whether this agent is marked
            hint_char: Optional jump hint character

        Returns:
            An Option for the OptionList
        """
        text = Text()
        if hint_char is not None:
            text.append(f"[{hint_char}] ", style="bold #FFFF00")

        if is_marked:
            text.append("[✓] ", style="bold #00D700")

        # Approve icon for autonomous agents
        if agent.approve:
            text.append(f"{_APPROVE_ICON} ", style="bold #00FFFF")

        # Indentation for retry-chain attempts: render under the chain
        # root so the user sees the lineage at a glance.  retry_attempt
        # tracks chain depth (1 = first retry, 2 = retry-of-retry, …).
        if agent.retry_attempt > 0 and not agent.is_workflow_child:
            indent = "  " * agent.retry_attempt + "↳ "
            text.append(indent, style="dim #808080")

        # Indentation for workflow child agents
        if agent.is_workflow_child:
            text.append(_CHILD_INDENT, style="dim #808080")
            # Add step number if available
            if agent.step_index is not None:
                if (
                    agent.parent_step_index is not None
                    and agent.parent_total_steps is not None
                ):
                    # Embedded step: format as "1a/7"
                    parent_num = agent.parent_step_index + 1
                    suffix = get_substep_suffix(agent.step_index)
                    text.append(
                        f"{parent_num}{suffix}/{agent.parent_total_steps} ",
                        style="dim #AAAAAA",
                    )
                elif agent.total_steps is not None:
                    # Regular step: format as "1/3" or "1/3.plan"
                    step_num = agent.step_index + 1
                    role = _step_role_suffix(agent)
                    text.append(
                        f"{step_num}/{agent.total_steps}{role} ", style="dim #AAAAAA"
                    )

        # Hidden icon for agents that are normally hidden
        if agent.hidden:
            text.append(f"{_HIDDEN_ICON} ", style="bold #FF5F87")

        # Pin icon for pinned agents (only in main panel; pinned panel has it in title)
        if is_pinned and self._panel != "pinned":
            text.append(f"{_PIN_ICON} ", style="bold #FFD700")

        # Done icon for dismissible agents (skip in pinned panel — redundant)
        if agent.status in _DISMISSIBLE_STATUSES and self._panel != "pinned":
            text.append(f"{_DONE_ICON} ", style="bold red")

        # Spawn-on-retry: prefix retry attempts with a small ↻N badge so
        # the user can pattern-match the chain depth without opening the
        # detail panel.  retry_attempt == 0 means "not a retry" and is not
        # rendered.
        if agent.retry_attempt > 0:
            badge_color = "#FFAF00"  # warm yellow
            text.append(f"↻{agent.retry_attempt} ", style=f"bold {badge_color}")

        # Agent type indicator with color
        dt = agent.get_display_type(is_expanded=is_expanded)

        # Color: RUNNING blue for appears_as_agent, per-step-type for workflow children
        if agent.appears_as_agent and not (agent.is_anonymous and is_expanded):
            color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
        elif agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
            color = _STEP_TYPE_COLORS[agent.step_type]
        else:
            color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")
        text.append(f"[{dt}] ", style=f"bold {color}")

        # Agent display name (workflow name for top-level workflows, CL name otherwise)
        name_style = "bold #00D7AF" if is_selected else "#00D7AF"
        text.append(agent.display_name, style=name_style)

        # Status (wrapped in parentheses, parens are dim)
        text.append(" (", style="dim")
        if agent.status == "RUNNING":
            text.append(agent.status, style="bold #FFD700")  # Gold
        elif agent.status in ("DONE", "PLAN DONE"):
            text.append(agent.status, style="bold #5FD75F")  # Green
        elif agent.status == "EPIC CREATED":
            text.append(agent.status, style="bold #5FD7AF")  # Sea-green
        elif agent.status == "FAILED":
            text.append(agent.status, style="bold #FF5F5F")  # Red
        elif agent.status == "FAILED (RETRIED)":
            # Spawn-on-retry: dim red + warm yellow ↻ glyph indicates a
            # terminal failure that handed off to a downstream retry, as
            # opposed to a dead-end failure with no recovery attempt.
            text.append("FAILED ", style="dim #FF5F5F")
            text.append("↻", style="bold #FFAF00")
            text.append(" (RETRIED)", style="dim #FF5F5F")
        elif agent.status == "PLANNING":
            text.append(agent.status, style="bold #FF87AF")  # Pink
        elif agent.status == "PLAN APPROVED":
            text.append(agent.status, style="bold #00D7AF")  # Green-blue (teal)
        elif agent.status == "WAITING":
            text.append(agent.status, style="bold #AF87FF")  # Amethyst
            # Live countdown for absolute-time waits
            if agent.wait_until:
                from datetime import datetime as _dt

                from sase.ace.tui.models.agent import format_wait_until

                target_label = format_wait_until(agent.wait_until)
                target = _dt.fromisoformat(agent.wait_until)
                remaining = (target - _dt.now()).total_seconds()
                if remaining > 0:
                    text.append(
                        f" (until {target_label}, {format_compact_duration(remaining)})",
                        style="#AF87FF",
                    )
                else:
                    text.append(f" (until {target_label})", style="#AF87FF")
            # Live countdown for duration-based waits
            elif agent.wait_duration and agent.start_time:
                from datetime import datetime, timedelta

                target = agent.start_time + timedelta(seconds=agent.wait_duration)
                remaining = (target - datetime.now()).total_seconds()
                if remaining > 0:
                    text.append(
                        f" ({format_compact_duration(remaining)})",
                        style="#AF87FF",
                    )
        elif agent.status == "QUESTION":
            text.append(agent.status, style="bold #FFAF00")  # Amber/orange
        elif agent.status == "RETRYING":
            # Compute countdown from retry_next_at_epoch
            countdown = ""
            if agent.retry_next_at_epoch:
                import time

                remaining = max(0, int(agent.retry_next_at_epoch - time.time()))
                countdown = f" ({remaining}s)"
            text.append(f"RETRYING{countdown}", style="bold #FF8700")  # Orange
        else:
            text.append(agent.status, style="dim")
        text.append(")", style="dim")

        # Retry/fallback annotations for RUNNING agents that have retried
        if agent.status == "RUNNING" and agent.retry_count > 0:
            annotation = f" \u21bb{agent.retry_count}"
            if agent.using_fallback and agent.fallback_model:
                short_name = _short_model_name(agent.fallback_model)
                annotation += f"\u25b8{short_name}"
            text.append(annotation, style="bold #FF8700")  # Orange

        # Fold annotation for workflow parents
        if fold_annotation:
            if "hidden" in fold_annotation or "shown" in fold_annotation:
                # EXPANDED/FULLY_EXPANDED: "(N steps, M hidden/shown)" in dim
                text.append(fold_annotation, style="dim")
            else:
                # COLLAPSED: "(N steps)" in dim cyan
                text.append(fold_annotation, style="dim #00D7D7")

        # User-managed tag badge (compact: "@first +N" when multiple)
        if agent.tags:
            primary = agent.tags[0]
            extra = len(agent.tags) - 1
            badge = f" @{primary}" + (f" +{extra}" if extra else "")
            text.append(badge, style="bold #5FAFFF")  # Sky blue

        # Agent name annotation
        if agent.agent_name:
            text.append(f" @{agent.agent_name}", style="#FFD700")  # Gold

        # Embedded workflow annotation for child steps
        if agent.embedded_workflow_name:
            text.append("  ", style="")
            if agent.is_pre_prompt_step:
                text.append("\u25b2 ", style="bold #5F87AF")
            else:
                text.append("\u25bc ", style="bold #D7AF5F")
            text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

        return Option(text, id=f"{index}:{agent.agent_type.value}:{agent.cl_name}")

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
                    panel=self._panel,
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
                    panel=self._panel,
                    attempt_number=attempt_number,
                    group_key=group_key,
                )
            )

    def _resolve_row(
        self, option_index: int
    ) -> tuple[int, int | None, tuple[str, ...] | None]:
        """Translate a raw OptionList row index to selection state.

        Returns ``(agent_local_idx, attempt_number, group_key)``.  When a
        selectable banner row is hit (group fold level < 3) the
        ``group_key`` is the banner's :attr:`GroupRow.group_key` and
        ``agent_local_idx`` points at the first agent in the group so
        the detail panel still has something to show.  When a banner is
        non-selectable (group fold level == 3) the row resolves to the
        next agent row exactly like in Phase 3.
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

    def _format_banner_option(
        self,
        group: GroupRow,
        *,
        width: int,
        sequence: int,
        selectable: bool = False,
    ) -> Option:
        """Render a group banner row Option.

        Banner styling per level:

        - L0 (tag): heavy double rule ``══`` in warm yellow.
        - L1 (project): single rule ``──`` in sky blue.
        - L2 (name-root): dim center-dot rule ``· name ·`` in muted gray.

        Banner Options are marked ``disabled`` (Phase 3) so OptionList
        cursor navigation skips them.  When *selectable* is True (Phase 4
        fold level < 3) the banner stays in the cursor flow and shows a
        compact summary chip after the label.
        """
        label = banner_label(group)
        summary = compute_banner_summary(group, self._agents)
        chip = banner_summary_text(summary)
        if group.level == 0:
            rule = "═"
            style = _TAG_BANNER_STYLE
            head_text = f"{rule}{rule} {label} "
        elif group.level == 1:
            rule = "─"
            style = _PROJECT_BANNER_STYLE
            head_text = f"{rule}{rule} {label} "
        else:
            rule = " "
            style = _NAME_ROOT_BANNER_STYLE
            head_text = f"· {label} ·"
        chip_text = f"{chip} " if chip else ""
        # Pad with the rule character to reach the target width, leaving
        # room for the summary chip rendered before the trailing rule run.
        pad_len = max(0, width - len(head_text) - len(chip_text))
        text = Text()
        text.append(head_text, style=style)
        if chip_text:
            text.append(chip_text, style=style)
        text.append(rule * pad_len, style=style)
        # Sequence-prefixed id keeps banner Options unique even when the
        # same group key is split into multiple non-contiguous clusters.
        key_str = "/".join(group.group_key)
        return Option(
            text,
            id=f"group:{sequence}:{group.level}:{key_str}",
            disabled=not selectable,
        )

    def _format_attempt_option(
        self,
        agent: Agent,
        record: AttemptRecord,
        *,
        is_selected: bool,
    ) -> Option:
        """Format a prior-attempt row as a selectable child of ``agent``."""
        text = Text()
        text.append("    ↳ ", style="dim #808080")
        label_style = "bold #FF8700" if is_selected else "#FF8700"
        text.append(f"Attempt {record.attempt_number}", style=label_style)
        try:
            hhmmss = record.start_hhmmss
        except (ValueError, OSError):
            hhmmss = "??:??:??"
        text.append(f" · {hhmmss}", style="dim #FF8700")
        if record.used_fallback:
            text.append(" (fallback)", style="dim #FF8700")
        text.append(f" · {record.status}", style="dim #FF8700")
        if record.error_snippet:
            text.append(f": {record.error_snippet}", style="dim italic #FF5F5F")
        option_id = f"attempt:{agent.raw_suffix}:{record.attempt_number}"
        return Option(text, id=option_id)


def _compute_fold_annotation(
    agent: Agent,
    fold_counts: dict[str, tuple[int, int]] | None,
    parents_with_visible_children: set[str],
    fully_expanded_parents: set[str] | None = None,
) -> str:
    """Compute fold annotation for a workflow parent.

    Args:
        agent: The agent to annotate.
        fold_counts: Fold counts mapping raw_suffix -> (non_hidden, hidden).
        parents_with_visible_children: Set of parent raw_suffixes that have
            visible children in the current filtered list.
        fully_expanded_parents: Set of parent raw_suffixes that are in
            FULLY_EXPANDED state (hidden children are visible).

    Returns:
        Annotation string, or empty string if not applicable.
    """
    attempts_count = len(agent.attempt_history)

    if _is_foldable_parent(agent) and fold_counts and agent.raw_suffix:
        counts = fold_counts.get(agent.raw_suffix)
        if counts:
            non_hidden, hidden = counts
            total = non_hidden + hidden
            if total > 0:
                has_visible_children = agent.raw_suffix in parents_with_visible_children
                suffix = _attempt_count_suffix(attempts_count)
                if not has_visible_children:
                    if (
                        agent.is_anonymous
                        and agent.appears_as_agent
                        and total == 1
                        and attempts_count == 0
                    ):
                        return ""
                    return f" ({total} steps{suffix})"
                is_fully_expanded = (
                    fully_expanded_parents is not None
                    and agent.raw_suffix in fully_expanded_parents
                )
                if hidden > 0 and is_fully_expanded:
                    return f" ({total} steps, {hidden} shown{suffix})"
                if hidden > 0:
                    return f" ({total} steps, {hidden} hidden{suffix})"
                if attempts_count > 0:
                    return f" ({attempts_count} attempts)"
                return ""

    # Non-workflow agent: annotate attempts alone when present.
    if attempts_count > 0:
        return f" ({attempts_count} attempts)"
    return ""


def _attempt_count_suffix(attempts_count: int) -> str:
    """Return ``, N attempts`` fragment when attempts exist, else empty string."""
    if attempts_count <= 0:
        return ""
    return f", {attempts_count} attempts"
