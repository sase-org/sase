"""Agent list widget for the ace TUI."""

from typing import Any, Literal

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from sase.xprompt.workflow_output import get_substep_suffix

from ..models.agent import Agent, AgentType, AttemptRecord, format_compact_duration

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
        """

        def __init__(
            self,
            index: int,
            panel: PanelId = "main",
            attempt_number: int | None = None,
        ) -> None:
            self.index = index
            self.panel = panel
            self.attempt_number = attempt_number
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
        """
        self._programmatic_update = True
        self._agents = agents
        self.clear_options()
        self._row_entries = []

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

        max_width = 0
        highlighted_row: int | None = None
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
            self.add_option(option)
            if is_selected_agent:
                highlighted_row = len(self._row_entries)
            self._row_entries.append((i, None))
            width = option.prompt.cell_len  # type: ignore[union-attr]
            max_width = max(max_width, width)

            # Emit attempt child rows below the agent row when the agent has
            # prior attempt records. Each is selectable and routes the detail
            # panel to an attempt-pinned view. Skip workflow child steps:
            # attempts belong to the workflow as a whole, so emitting them under
            # each child would both produce duplicate option IDs and misattribute
            # attempts to individual steps.
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
                    self.add_option(attempt_option)
                    if is_selected_attempt:
                        highlighted_row = len(self._row_entries)
                    self._row_entries.append((i, record.attempt_number))
                    width = attempt_option.prompt.cell_len  # type: ignore[union-attr]
                    max_width = max(max_width, width)

        # Add padding for border, scrollbar, visual comfort (~8 cells)
        _PADDING = 8
        optimal_width = max_width + _PADDING
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
        elif agent.status == "FAILED":
            text.append(agent.status, style="bold #FF5F5F")  # Red
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
            agent_idx, attempt_number = self._resolve_row(event.option_index)
            self.post_message(
                self.SelectionChanged(
                    agent_idx, panel=self._panel, attempt_number=attempt_number
                )
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if event.option_index is not None:
            agent_idx, attempt_number = self._resolve_row(event.option_index)
            self.post_message(
                self.SelectionChanged(
                    agent_idx, panel=self._panel, attempt_number=attempt_number
                )
            )

    def _resolve_row(self, option_index: int) -> tuple[int, int | None]:
        """Translate a raw OptionList row index to (agent_local_idx, attempt_number)."""
        if 0 <= option_index < len(self._row_entries):
            return self._row_entries[option_index]
        return (option_index, None)

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
