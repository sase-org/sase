"""Agent row rendering — builds the ``(left, suffix, option_id)`` parts
for one agent in the list, plus a memoized wrapper backed by
:class:`AgentRenderCache`.
"""

from collections.abc import Collection
from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)

from ..agent_count_chip import format_agent_count_chip
from ..models._agent_clan import (
    ClanStatusCounts as ParallelFamilyStatusCounts,
    clan_member_counts as parallel_family_member_counts,
)
from ..models._agent_tree import agent_is_tree_child, agent_tree_depth
from ..provider_styles import provider_emoji_badge
from ..models.agent import (
    Agent,
    AgentType,
    format_compact_duration,
    format_wait_until,
    wait_display_agent,
    wait_remaining_seconds,
)
from ..models.agent_status import STOPPED_COLOR, STOPPED_GLYPH, STOPPED_STATUS
from ..models.agent_bead import agent_has_confirmed_bead
from ._agent_list_helpers import (
    ordered_row_providers,
    short_model_name,
)
from ._agent_list_render_cache import (
    AgentRenderCache,
    agent_file_change_hint,
    agent_render_key,
)
from ._agent_list_render_layout import (
    build_activity_suffix,
    build_runtime_suffix,
    combine_suffixes,
    render_tier_gutter,
)
from ._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _BEAD_GLYPH,
    _BEAD_GLYPH_STYLE,
    _CHILD_INDENT,
    _CLAN_GLYPH,
    _CLAN_GLYPH_STYLE,
    _FAMILY_GLYPH,
    _FAMILY_GLYPH_STYLE,
    _FILE_CHANGE_GLYPH,
    _FILE_CHANGE_GLYPH_STYLE,
    _HIDDEN_ICON,
    _REVERTED_GLYPH,
    _REVERTED_GLYPH_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TYPE_GLYPHS,
    _TREE_GUIDE,
)


def _should_render_provider_badge(agent: Agent) -> bool:
    return not (agent.is_child_row and not agent.is_agent_entry)


def _has_file_change_hint(agent: Agent) -> bool:
    return agent_file_change_hint(agent)


def _should_render_reverted_badge(agent: Agent) -> bool:
    return agent.reverted and not agent_is_tree_child(agent)


def _append_tree_indent(text: Text, depth: int) -> None:
    """Append a depth-aware branch using the existing child-row footprint."""
    if depth <= 0:
        return
    if depth == 1:
        indent = _CHILD_INDENT
    else:
        indent = "  " + (_TREE_GUIDE * (depth - 1)) + _CHILD_INDENT.lstrip()
    text.append(indent, style="dim #808080")


def format_agent_option(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    is_unread: bool = False,
    hint_char: str | None = None,
    tag_label: str | None = None,
    panel_tag: str | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    wait_deps_satisfied: bool | None = None,
    parallel_family_counts: ParallelFamilyStatusCounts | None = None,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for an agent row."""
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
        _append_tree_indent(text, tree_depth)
        if approve_icon is not None:
            text.append(f"{approve_icon} ", style="bold #00FFFF")
        if agent.is_workflow_step_child:
            step_glyph = _STEP_TYPE_GLYPHS.get(agent.step_type or "")
            if step_glyph is not None:
                glyph_color = _STEP_TYPE_COLORS.get(agent.step_type or "", "#FFFFFF")
                text.append(f"{step_glyph} ", style=f"bold {glyph_color}")

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

    # Color: RUNNING blue for appears_as_agent, per-step-type for workflow steps.
    is_appears_as_agent = agent.appears_as_agent and not (
        agent.is_anonymous and is_expanded
    )
    if is_appears_as_agent:
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
    if not (agent.is_clan_container or agent.is_family_container_row) and not (
        is_appears_as_agent or agent_is_tree_child(agent)
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
        if is_reverted_root:
            text.append(_REVERTED_GLYPH, style=_REVERTED_GLYPH_STYLE)
            text.append(" ")
            name_style = "bold strike #00D7AF" if is_selected else "strike #00D7AF"
        else:
            name_style = "bold #00D7AF" if is_selected else "#00D7AF"

        # Agent display name (workflow name for top-level workflows,
        # ChangeSpec name otherwise).
        text.append(agent.display_name, style=name_style)
        if tag_label:
            text.append(f" @{tag_label}", style="bold #FFD75F")

    # Status (wrapped in parentheses, parens are dim)
    display_status = agent.display_status
    row_prefix = text.plain
    status_opener = "(" if not row_prefix or row_prefix[-1].isspace() else " ("
    text.append(status_opener, style="dim")
    if agent.status == "STARTING":
        text.append(display_status, style="bold #87D7FF")  # Sky blue
    elif agent.status == "RUNNING":
        text.append(display_status, style="bold #FFD700")  # Gold
    elif agent.status in ("DONE", "PLAN DONE", "TALE DONE"):
        text.append(display_status, style="bold #5FD75F")  # Green
    elif agent.status == "PLAN REJECTED":
        text.append(display_status, style="bold #D7AF5F")  # Muted gold
    elif agent.status == STOPPED_STATUS:
        text.append(
            f"{STOPPED_GLYPH} {display_status}",
            style=f"bold {STOPPED_COLOR}",
        )
    elif agent.status == "EPIC CREATED":
        text.append(display_status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == "FAILED":
        text.append(display_status, style="bold #FF5F5F")  # Red
    elif agent.status == "FAILED (RETRIED)":
        # Spawn-on-retry: dim red + warm yellow ↻ glyph indicates a
        # terminal failure that handed off to a downstream retry, as
        # opposed to a dead-end failure with no recovery attempt.
        text.append("FAILED ", style="dim #FF5F5F")
        text.append("↻", style="bold #FFAF00")
        text.append(" (RETRIED)", style="dim #FF5F5F")
    elif agent.status == "PLAN":
        text.append(display_status, style="bold #FF87AF")  # Pink
    elif agent.status == FEEDBACK_STATUS:
        text.append(display_status, style="bold #FF5FD7")  # Magenta
    elif agent.status == PLAN_APPROVED_STATUS:
        text.append(display_status, style="bold #00D7AF")  # Green-blue (teal)
    elif agent.status == TALE_APPROVED_STATUS:
        text.append(display_status, style="bold #00D7D7")  # Turquoise
    elif agent.status == WORKING_PLAN_STATUS:
        text.append(display_status, style="bold #00AF87")  # Deep teal
    elif agent.status == WORKING_TALE_STATUS:
        text.append(display_status, style="bold #00AFAF")  # Deep turquoise
    elif agent.status == "PLAN COMMITTED":
        text.append(display_status, style="bold #5FD75F")  # Green
    elif agent.status == "EPIC APPROVED":
        text.append(display_status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == "WAITING":
        text.append(display_status, style="bold #AF87FF")  # Amethyst
        wait_agent = wait_display_agent(agent)
        if (
            wait_agent.slot_requested_at
            and wait_agent.wait_runners is not None
            and wait_agent.runner_slots_in_use is not None
        ):
            if wait_agent.wait_runners_explicit:
                slot_label = (
                    f" ▶{wait_agent.runner_slots_in_use}→{wait_agent.wait_runners}"
                )
            else:
                slot_label = (
                    f" ▶{wait_agent.runner_slots_in_use}/{wait_agent.wait_runners + 1}"
                )
            text.append(slot_label, style="dim #AF87FF")
        deps_satisfied = (
            not wait_agent.waiting_for
            if wait_deps_satisfied is None
            else wait_deps_satisfied
        )
        wait_remaining = wait_remaining_seconds(agent, now=now)
        if wait_remaining is not None and wait_remaining > 0 and deps_satisfied:
            text.append(
                f" {format_compact_duration(wait_remaining)}",
                style="#AF87FF",
            )
        elif (
            wait_agent.waiting_for
            and wait_agent.wait_duration is not None
            and not wait_agent.wait_until
        ):
            text.append(
                f" +{format_compact_duration(wait_agent.wait_duration)}",
                style="#AF87FF",
            )
        elif wait_agent.wait_until:
            target_label = format_wait_until(wait_agent.wait_until, now=now)
            if wait_remaining is not None and wait_remaining > 0:
                text.append(
                    f" (until {target_label}, "
                    f"{format_compact_duration(wait_remaining)})",
                    style="#AF87FF",
                )
            else:
                text.append(f" (until {target_label})", style="#AF87FF")
    elif agent.status == "QUESTION":
        text.append(display_status, style="bold #FFAF00")  # Amber/orange
    elif agent.status == "ANSWERED":
        # Transient post-answer state: distinct bright azure, set apart from
        # QUESTION amber, RUNNING gold, and approved-plan teal.
        text.append(display_status, style="bold #5FD7FF")  # Bright cyan/azure
    elif agent.status == "RETRYING":
        countdown = ""
        if agent.retry_next_at_epoch:
            import time

            remaining = max(0, int(agent.retry_next_at_epoch - time.time()))
            countdown = f" ({remaining}s)"
        text.append(f"RETRYING{countdown}", style="bold #FF8700")  # Orange
    else:
        text.append(display_status, style="dim")
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

    family_counts = (
        (
            parallel_family_member_counts(agent, unread_agent_ids)
            if unread_agent_ids
            else parallel_family_member_counts(agent)
        )
        if parallel_family_counts is None
        else parallel_family_counts
    )
    family_chip = format_agent_count_chip(
        stopped=family_counts.awaiting,
        running=family_counts.running,
        waiting=family_counts.waiting,
        failed=family_counts.failed,
        unread=family_counts.unread,
        done=family_counts.done,
    )
    if family_chip:
        text.append(" ")
        text.append_text(family_chip)

    # Authoritative-only: modern phase launch metadata renders immediately;
    # legacy candidates render after an O(1) confirmed-cache read warmed off
    # the event loop. Cold or missing legacy candidates render no glyph.
    if not agent.is_clan_container and agent_has_confirmed_bead(agent):
        text.append(" ")
        text.append(_BEAD_GLYPH, style=_BEAD_GLYPH_STYLE)

    # Shared trailing identity block. Grouping icons remain attached to the
    # gold name they identify; bead context, when present, stays to the left.
    identity_glyph: str | None = None
    identity_glyph_style: str | None = None
    presented_name: str | None
    if agent.is_clan_container:
        identity_glyph = _CLAN_GLYPH
        identity_glyph_style = _CLAN_GLYPH_STYLE
        presented_name = agent.display_name
    else:
        presented_name = agent.presented_agent_name or agent.agent_name
        if agent.is_family_container_row:
            identity_glyph = _FAMILY_GLYPH
            identity_glyph_style = _FAMILY_GLYPH_STYLE

    if identity_glyph or presented_name:
        text.append(" ")
        if identity_glyph:
            text.append(identity_glyph, style=identity_glyph_style)
            if presented_name:
                text.append(" ")
        if presented_name:
            text.append(presented_name, style=_AGENT_NAME_ANNOTATION_STYLE)

    if agent.is_clan_container:
        rendered_tags = tuple(
            dict.fromkeys(tag for tag in agent.clan_tags if tag != panel_tag)
        )
        for clan_tag in rendered_tags:
            text.append(f" @{clan_tag}", style="bold #FFD75F")
        if tag_label and tag_label not in rendered_tags:
            text.append(f" @{tag_label}", style="bold #FFD75F")

    # Embedded workflow annotation for child steps
    if agent.embedded_workflow_name:
        text.append(" ", style="")
        if agent.is_pre_prompt_step:
            text.append("▲", style="bold #5F87AF")
        else:
            text.append("▼", style="bold #D7AF5F")
        text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

    runtime_suffix = build_runtime_suffix(agent, now=now, is_unread=is_unread)
    if not agent.is_clan_container and _has_file_change_hint(agent):
        runtime_with_file_change = Text()
        if runtime_suffix.cell_len:
            runtime_with_file_change.append_text(runtime_suffix)
            runtime_with_file_change.append(" ")
        runtime_with_file_change.append(
            _FILE_CHANGE_GLYPH,
            style=_FILE_CHANGE_GLYPH_STYLE,
        )
    else:
        runtime_with_file_change = runtime_suffix

    suffix = combine_suffixes(
        build_activity_suffix(agent),
        runtime_with_file_change,
    )
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
    is_unread: bool = False,
    hint_char: str | None = None,
    tag_label: str | None = None,
    panel_tag: str | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    wait_deps_satisfied: bool | None = None,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> tuple[Text, Text, str]:
    """Memoized wrapper for :func:`format_agent_option`.

    Reuses ``(left, suffix, option_id)`` from *cache* when every input
    matches a prior call. ``Text`` objects from Rich are immutable for
    our purposes (we don't mutate them after assemble); returning the
    cached object avoids rebuilding an O(rows) Text tree on each refresh.
    """
    family_counts = (
        parallel_family_member_counts(agent, unread_agent_ids)
        if unread_agent_ids
        else parallel_family_member_counts(agent)
    )
    key = agent_render_key(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        is_unread=is_unread,
        hint_char=hint_char,
        tag_label=tag_label,
        panel_tag=panel_tag,
        now=now,
        tier_styles=tier_styles,
        wait_deps_satisfied=wait_deps_satisfied,
        parallel_family_counts=family_counts,
        unread_agent_ids=unread_agent_ids,
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
        is_unread=is_unread,
        hint_char=hint_char,
        tag_label=tag_label,
        panel_tag=panel_tag,
        now=now,
        tier_styles=tier_styles,
        wait_deps_satisfied=wait_deps_satisfied,
        parallel_family_counts=family_counts,
        unread_agent_ids=unread_agent_ids,
    )
    cache.put_agent(key, parts)
    return parts
