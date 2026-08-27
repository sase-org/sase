"""Leading chrome for one agent-list row.

Owns the gutter, marks, type/provider badges, and left-side title that
precede the status parenthetical in :func:`format_agent_option`.
"""

from collections.abc import Mapping

from rich.text import Text

from ..models._agent_tree import agent_is_tree_child, agent_tree_depth, agent_tree_title
from ..models.agent import Agent, AgentType
from ..models.agent_family_members import gate_row_is_settled, monitor_row_is_settled
from ..models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
)
from ..provider_styles import provider_emoji_badge
from ._agent_list_helpers import ordered_row_providers
from ._agent_list_render_layout import render_tier_gutter
from ._agent_list_styling import (
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _CHILD_INDENT,
    _GATE_FAILED_COUNT_GLYPH_STYLE,
    _GATE_GLYPH,
    _GATE_ROW_STYLE,
    _GATE_SETTLED_COUNT_GLYPH_STYLE,
    _HIDDEN_ICON,
    _MONITOR_GLYPH,
    _MONITOR_GLYPH_STYLE,
    _MONITOR_ROW_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
    _PROC_SHELL_GLYPH,
    _PROC_SHELL_GLYPH_STYLE,
    _PROC_SHELL_ROW_STYLE,
    _REVERTED_GLYPH,
    _REVERTED_GLYPH_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TREE_DEPTH_COLORS,
    _TREE_GUIDE,
    _TYPE_GLYPHS,
)


def _should_render_provider_badge(agent: Agent) -> bool:
    return not (agent.is_child_row and not agent.is_agent_entry)


def _should_render_reverted_badge(agent: Agent) -> bool:
    return agent.reverted and not agent_is_tree_child(agent)


def _monitor_glyph_style(agent: Agent) -> str:
    """Return the row gear style for a monitor shell.

    Shares ``monitor_row_is_settled`` with the ``⚙N`` lane counts so a grey
    gear on a row and the grey count it feeds can never disagree.
    """
    return (
        _MONITOR_SETTLED_GLYPH_STYLE
        if monitor_row_is_settled(agent)
        else _MONITOR_GLYPH_STYLE
    )


def _gate_glyph_style(agent: Agent) -> str:
    """Return the row glyph style for a gate shell."""
    if agent.gate_state in {"failed", "timeout", "lost"}:
        return _GATE_FAILED_COUNT_GLYPH_STYLE
    if gate_row_is_settled(agent):
        return _GATE_SETTLED_COUNT_GLYPH_STYLE
    if agent.gate_accent:
        return f"bold {agent.gate_accent}"
    return _GATE_ROW_STYLE


def _tree_depth_style(depth: int, *, is_selected: bool) -> str:
    """Return the Rich style for a tree connector at one-based *depth*."""
    color = _TREE_DEPTH_COLORS[(depth - 1) % len(_TREE_DEPTH_COLORS)]
    return f"bold {color}" if is_selected else color


def _append_tree_indent(text: Text, depth: int, *, is_selected: bool) -> None:
    """Append a depth-aware branch using the existing child-row footprint.

    Leading spacing, each ancestor guide, and the terminal branch are
    separate spans so a connector keeps the color of the level it represents.
    """
    if depth <= 0:
        return
    text.append("  ")
    for ancestor_depth in range(1, depth):
        text.append(
            _TREE_GUIDE,
            style=_tree_depth_style(ancestor_depth, is_selected=is_selected),
        )
    text.append(
        _CHILD_INDENT.lstrip(),
        style=_tree_depth_style(depth, is_selected=is_selected),
    )


def tribe_style(
    tribe: str,
    tribe_colors: Mapping[str, str] | None,
) -> str:
    """Return the bold identity style for a ``@tribe`` annotation."""
    color = (
        tribe_colors.get(tribe, TRIBE_IDENTITY_FALLBACK_COLOR)
        if tribe_colors is not None
        else TRIBE_IDENTITY_FALLBACK_COLOR
    )
    return compose_tribe_identity_style(color, bold=True)


def append_agent_row_prefix(
    agent: Agent,
    *,
    is_selected: bool,
    is_expanded: bool = False,
    is_marked: bool = False,
    hint_char: str | None = None,
    tribe_label: str | None = None,
    tribe_colors: Mapping[str, str] | None = None,
    tier_styles: tuple[str, ...] = (),
) -> Text:
    """Build the left-side chrome that precedes the status parenthetical."""
    text = render_tier_gutter(tier_styles)
    tree_depth = agent_tree_depth(agent)
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    if is_marked:
        text.append("[✓] ", style="bold #00D700")

    # Approve icon for autonomous agents. The bare ``⚡`` marks a normal-plan
    # auto-approve; ``⚡E``/``⚡T`` distinguish the epic/tale plan actions.
    approve_icon: str | None = None
    if agent.approve:
        if agent.auto_approve_plan_action == "epic":
            approve_icon = f"{_APPROVE_ICON}E"
        elif agent.auto_approve_plan_action == "tale":
            approve_icon = f"{_APPROVE_ICON}T"
        else:
            approve_icon = _APPROVE_ICON
    if approve_icon is not None and tree_depth == 0:
        text.append(f"{approve_icon} ", style="bold #00FFFF")

    # Indentation for retry-chain attempts: render under the chain
    # root so the user sees the lineage at a glance.  retry_attempt
    # tracks chain depth (1 = first retry, 2 = retry-of-retry, …).
    if agent.retry_attempt > 0 and tree_depth == 0:
        indent = "  " * agent.retry_attempt + "↳ "
        text.append(indent, style="dim #808080")

    # Indentation for rows linked under a parent agent/workflow.
    if tree_depth > 0:
        _append_tree_indent(text, tree_depth, is_selected=is_selected)
        if approve_icon is not None:
            text.append(f"{approve_icon} ", style="bold #00FFFF")
        if agent.is_monitor:
            text.append(f"{_MONITOR_GLYPH} ", style=_monitor_glyph_style(agent))
        elif agent.is_gate:
            text.append(f"{_GATE_GLYPH} ", style=_gate_glyph_style(agent))
        elif agent.is_workflow_step_child:
            step_glyph = _STEP_TYPE_GLYPHS.get(agent.step_type or "")
            if step_glyph is not None:
                glyph_color = _STEP_TYPE_COLORS.get(agent.step_type or "", "#FFFFFF")
                text.append(f"{step_glyph} ", style=f"bold {glyph_color}")
    elif agent.is_monitor:
        text.append(f"{_MONITOR_GLYPH} ", style=_monitor_glyph_style(agent))
    elif agent.is_gate:
        text.append(f"{_GATE_GLYPH} ", style=_gate_glyph_style(agent))
    elif agent.is_proc_shell:
        text.append(f"{_PROC_SHELL_GLYPH} ", style=_PROC_SHELL_GLYPH_STYLE)

    # Hidden icon for agents that are normally hidden
    if agent.hidden:
        text.append(f"{_HIDDEN_ICON} ", style="bold #FF5F87")

    # Spawn-on-retry: prefix retry attempts with a small ↻N badge so
    # the user can pattern-match the chain depth without opening the
    # detail panel.  retry_attempt == 0 means "not a retry" and is not
    # rendered.
    if agent.retry_attempt > 0:
        badge_color = "#FFAF00"  # warm yellow
        text.append(f"↻{agent.retry_attempt} ", style=f"bold {badge_color}")

    # Agent type indicator with color
    dt = agent.get_display_type(is_expanded=is_expanded)
    is_family_container_row = agent.is_family_container_row

    # Color: RUNNING blue for appears_as_agent, per-step-type for workflow steps.
    is_appears_as_agent = agent.appears_as_agent and not (
        agent.is_anonymous and is_expanded
    )
    if agent.is_monitor:
        color = _MONITOR_ROW_STYLE
    elif agent.is_gate:
        color = _gate_glyph_style(agent).removeprefix("bold ")
    elif agent.is_proc_shell:
        color = _PROC_SHELL_ROW_STYLE
    elif is_appears_as_agent:
        color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
    elif agent.is_workflow_step_child and agent.step_type in _STEP_TYPE_COLORS:
        color = _STEP_TYPE_COLORS[agent.step_type]
    else:
        color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")

    # Compact type prefix: ``agent``-typed rows omit the bracket entirely
    # (their color already encodes the type and the workflow-child indent
    # already marks tree depth).  Other top-level types render as a
    # single-glyph badge; unknown types fall back to ``[X] `` for debug
    # readability.
    if not (agent.is_clan_container or is_family_container_row) and not (
        is_appears_as_agent
        or agent_is_tree_child(agent)
        or agent.is_monitor
        or agent.is_gate
        or agent.is_proc_shell
    ):
        type_glyph = _TYPE_GLYPHS.get(dt)
        if type_glyph is not None:
            text.append(f"{type_glyph} ", style=f"bold {color}")
        else:
            text.append(f"[{dt}] ", style=f"bold {color}")

    if _should_render_provider_badge(agent):
        for provider in ordered_row_providers(agent):
            emoji_badge = provider_emoji_badge(provider)
            if emoji_badge:
                text.append(f"{emoji_badge} ")

    if not agent.is_clan_container:
        is_reverted_root = _should_render_reverted_badge(agent)
        if agent.is_proc_shell:
            name_style = f"bold {color}" if is_selected else color
        elif is_reverted_root:
            text.append(_REVERTED_GLYPH, style=_REVERTED_GLYPH_STYLE)
            text.append(" ")
            name_style = "bold strike #00D7AF" if is_selected else "strike #00D7AF"
        else:
            name_style = "bold #00D7AF" if is_selected else "#00D7AF"

        # Bash/python workflow steps keep their step name as identity. Sase
        # shells (family members, monitors, workflow agent steps) omit the
        # left-side title; identity is the right-hand %id annotation.
        title = agent_tree_title(agent)
        if title:
            text.append(title, style=name_style)
        if tribe_label:
            text.append(
                f" @{tribe_label}",
                style=tribe_style(tribe_label, tribe_colors),
            )

    return text
