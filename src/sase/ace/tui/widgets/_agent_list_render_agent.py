"""Agent row rendering — builds the ``(left, suffix, option_id)`` parts
for one agent in the list, plus a memoized wrapper backed by
:class:`AgentRenderCache`.
"""

from datetime import datetime

from rich.text import Text

from sase.xprompt.workflow_output import get_substep_suffix

from ..models.agent import Agent, AgentType, format_compact_duration
from ..models.agent_bead import derive_agent_bead_id
from ..models.artifact_indicator import (
    ArtifactIndicator,
    render_artifact_indicator,
)
from ._agent_list_helpers import short_model_name, step_role_suffix
from ._agent_list_render_cache import AgentRenderCache, agent_render_key
from ._agent_list_render_layout import build_runtime_suffix, render_tier_gutter
from ._agent_list_styling import (
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _BEAD_GLYPH,
    _BEAD_GLYPH_STYLE,
    _BEAD_TEXT_STYLE,
    _CHILD_INDENT,
    _HIDDEN_ICON,
    _STEP_TYPE_COLORS,
    _TYPE_GLYPHS,
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
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    artifact_indicator: ArtifactIndicator | None = None,
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for an agent row."""
    text = render_tier_gutter(tier_styles)
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    if is_marked:
        text.append("[✓] ", style="bold #00D700")

    # Approve icon for autonomous agents
    if agent.approve:
        icon = (
            f"{_APPROVE_ICON}E"
            if agent.auto_approve_plan_action == "epic"
            else _APPROVE_ICON
        )
        text.append(f"{icon} ", style="bold #00FFFF")

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
                substep = get_substep_suffix(agent.step_index)
                text.append(
                    f"{parent_num}{substep}/{agent.parent_total_steps} ",
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
    is_appears_as_agent = agent.appears_as_agent and not (
        agent.is_anonymous and is_expanded
    )
    if is_appears_as_agent:
        color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
    elif agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
        color = _STEP_TYPE_COLORS[agent.step_type]
    else:
        color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")

    # Compact type prefix: ``agent``-typed rows omit the bracket entirely
    # (their color already encodes the type and the workflow-child indent
    # already marks tree depth).  Other top-level types render as a
    # single-glyph badge; unknown types fall back to ``[X] `` for debug
    # readability.
    if not (is_appears_as_agent or agent.is_workflow_child):
        type_glyph = _TYPE_GLYPHS.get(dt)
        if type_glyph is not None:
            text.append(f"{type_glyph} ", style=f"bold {color}")
        else:
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
    elif agent.status == "PLAN REJECTED":
        text.append(agent.status, style="bold #D7AF5F")  # Muted gold
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
    elif agent.status == "PLAN COMMITTED":
        text.append(agent.status, style="bold #5FD75F")  # Green
    elif agent.status == "EPIC APPROVED":
        text.append(agent.status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == "LEGEND APPROVED":
        text.append(agent.status, style="bold #D7AFFF")  # Lavender
    elif agent.status == "WAITING":
        text.append(agent.status, style="bold #AF87FF")  # Amethyst
        if agent.wait_until:
            from sase.ace.tui.models.agent import (
                format_wait_until,
                wait_until_target_and_reference,
            )

            target_label = format_wait_until(agent.wait_until)
            target, reference = wait_until_target_and_reference(agent.wait_until)
            remaining = (target - reference).total_seconds()
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

    # Fold annotation for workflow parents.  ``×N +M`` / ``×N −M`` (with
    # extra hidden/shown info) renders dim; the bare ``×N`` collapsed
    # form keeps its dim-cyan accent so the count still pops.
    if fold_annotation:
        if "+" in fold_annotation or "−" in fold_annotation:
            text.append(fold_annotation, style="dim")
        else:
            text.append(fold_annotation, style="dim #00D7D7")

    bead_id = derive_agent_bead_id(agent)
    if bead_id:
        text.append(" ")
        text.append(_BEAD_GLYPH, style=_BEAD_GLYPH_STYLE)
        text.append(f" {bead_id}", style=_BEAD_TEXT_STYLE)

    # User-managed tag badge.
    if agent.tag:
        text.append(f" @{agent.tag}", style="bold #5FAFFF")  # Sky blue

    # Agent name annotation
    if agent.agent_name:
        text.append(f" @{agent.agent_name}", style="#FFD700")  # Gold

    # Embedded workflow annotation for child steps
    if agent.embedded_workflow_name:
        text.append(" ", style="")
        if agent.is_pre_prompt_step:
            text.append("▲", style="bold #5F87AF")
        else:
            text.append("▼", style="bold #D7AF5F")
        text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

    artifact_text = render_artifact_indicator(artifact_indicator)
    if artifact_text.cell_len:
        text.append("  ", style="")
        text.append_text(artifact_text)

    suffix = build_runtime_suffix(agent, now=now)
    option_id = f"{index}:{agent.agent_type.value}:{agent.cl_name}"
    return text, suffix, option_id


def cached_format_agent_option(
    cache: AgentRenderCache,
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    hint_char: str | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    artifact_indicator: ArtifactIndicator | None = None,
) -> tuple[Text, Text, str]:
    """Memoized wrapper for :func:`format_agent_option`.

    Reuses ``(left, suffix, option_id)`` from *cache* when every input
    matches a prior call. ``Text`` objects from Rich are immutable for
    our purposes (we don't mutate them after assemble); returning the
    cached object avoids rebuilding an O(rows) Text tree on each refresh.
    """
    key = agent_render_key(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        hint_char=hint_char,
        now=now,
        tier_styles=tier_styles,
        artifact_indicator=artifact_indicator,
    )
    hit = cache.get_agent(key)
    if hit is not None:
        return hit
    parts = format_agent_option(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        hint_char=hint_char,
        now=now,
        tier_styles=tier_styles,
        artifact_indicator=artifact_indicator,
    )
    cache.put_agent(key, parts)
    return parts
