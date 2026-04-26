"""Rendering helpers that build Option rows for the agent list widget."""

from rich.text import Text
from textual.widgets.option_list import Option
from sase.xprompt.workflow_output import get_substep_suffix

from ..models.agent import Agent, AgentType, AttemptRecord, format_compact_duration
from ..models.agent_groups import (
    GroupRow,
    banner_label,
    banner_summary_text,
    compute_banner_summary,
)
from ._agent_list_helpers import short_model_name, step_role_suffix
from ._agent_list_styling import (
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _CHILD_INDENT,
    _DISMISSIBLE_STATUSES,
    _DONE_ICON,
    _HIDDEN_ICON,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAME_ROOT_BANNER_STYLE,
    _PROJECT_BANNER_STYLE,
    _STEP_TYPE_COLORS,
)


def format_agent_option(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    hint_char: str | None = None,
) -> Option:
    """Format an agent as an option for display."""
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
                role = step_role_suffix(agent)
                text.append(
                    f"{step_num}/{agent.total_steps}{role} ", style="dim #AAAAAA"
                )

    # Hidden icon for agents that are normally hidden
    if agent.hidden:
        text.append(f"{_HIDDEN_ICON} ", style="bold #FF5F87")

    # Done icon for dismissible agents
    if agent.status in _DISMISSIBLE_STATUSES:
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
        annotation = f" ↻{agent.retry_count}"
        if agent.using_fallback and agent.fallback_model:
            short_name = short_model_name(agent.fallback_model)
            annotation += f"▸{short_name}"
        text.append(annotation, style="bold #FF8700")  # Orange

    # Fold annotation for workflow parents
    if fold_annotation:
        if "hidden" in fold_annotation or "shown" in fold_annotation:
            # EXPANDED/FULLY_EXPANDED: "(N steps, M hidden/shown)" in dim
            text.append(fold_annotation, style="dim")
        else:
            # COLLAPSED: "(N steps)" in dim cyan
            text.append(fold_annotation, style="dim #00D7D7")

    # User-managed tag badge.
    if agent.tag:
        text.append(f" @{agent.tag}", style="bold #5FAFFF")  # Sky blue

    # Agent name annotation
    if agent.agent_name:
        text.append(f" @{agent.agent_name}", style="#FFD700")  # Gold

    # Embedded workflow annotation for child steps
    if agent.embedded_workflow_name:
        text.append("  ", style="")
        if agent.is_pre_prompt_step:
            text.append("▲ ", style="bold #5F87AF")
        else:
            text.append("▼ ", style="bold #D7AF5F")
        text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

    return Option(text, id=f"{index}:{agent.agent_type.value}:{agent.cl_name}")


def format_banner_option(
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
) -> Option:
    """Render a group banner row Option.

    Banner styling per level:

    - L0 (project): single rule ``──`` in sky blue.
    - L1 (name-root): dim center-dot rule ``· name ·`` in muted gray.

    Banner Options are marked ``disabled`` so OptionList cursor
    navigation skips them at full expansion.  When *selectable* is True
    (fold level < max) the banner stays in the cursor flow and shows a
    compact summary chip after the label.
    """
    label = banner_label(group)
    summary = compute_banner_summary(group, agents)
    chip = banner_summary_text(summary)
    chip_text = f"{chip} " if chip else ""
    text = Text()
    if group.level == 0:
        rule = "─"
        style = _PROJECT_BANNER_STYLE
        head_text = f"{rule}{rule} {label} "
        pad_len = max(0, width - len(head_text) - len(chip_text))
        text.append(head_text, style=style)
        if chip_text:
            text.append(chip_text, style=style)
        text.append(rule * pad_len, style=style)
    else:
        rule = " "
        decor_left = "· "
        decor_right = " ·"
        pad_len = max(
            0,
            width - len(decor_left) - len(label) - len(decor_right) - len(chip_text),
        )
        text.append(decor_left, style=_NAME_ROOT_BANNER_STYLE)
        text.append(label, style=_NAME_ROOT_BANNER_LABEL_STYLE)
        text.append(decor_right, style=_NAME_ROOT_BANNER_STYLE)
        if chip_text:
            text.append(chip_text, style=_NAME_ROOT_BANNER_STYLE)
        text.append(rule * pad_len, style=_NAME_ROOT_BANNER_STYLE)
    # Sequence-prefixed id keeps banner Options unique even when the
    # same group key is split into multiple non-contiguous clusters.
    key_str = "/".join(group.group_key)
    return Option(
        text,
        id=f"group:{sequence}:{group.level}:{key_str}",
        disabled=not selectable,
    )


def format_attempt_option(
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
