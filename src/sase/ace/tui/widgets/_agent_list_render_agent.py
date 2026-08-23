"""Agent row rendering — builds the ``(left, suffix, option_id)`` parts
for one agent in the list, plus a memoized wrapper backed by
:class:`AgentRenderCache`.
"""

from collections.abc import Collection, Mapping
from datetime import datetime

from rich.text import Text

from ..agent_completion import WaitDependencyStatusCounts
from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PENDING_EPIC_STATUS,
    PENDING_TALE_STATUS,
    PLAN_APPROVED_STATUS,
    QUEUED_STATUS,
    QUEUED_STATUS_COLOR,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)

from ..agent_count_chip import format_agent_count_chip
from ..models._agent_clan import ClanStatusCounts, clan_member_counts
from ..models._agent_tree import agent_is_tree_child, agent_tree_depth, agent_tree_title
from ..models.agent_nodes import is_agents_tab_agent_node
from ..provider_styles import provider_emoji_badge
from ..models.agent import (
    Agent,
    AgentType,
    format_compact_duration,
    format_wait_until,
    wait_display_agent,
    wait_remaining_seconds,
)
from ..models.agent_family_members import (
    NO_MONITOR_LANES,
    MonitorLaneCounts,
    is_sequential_family_container,
    monitor_lane_counts,
    monitor_row_is_settled,
)
from ..models.agent_status import (
    RUNNING_COLOR,
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from ..models.agent_bead import agent_has_confirmed_bead
from ..models.agent_panels import normalize_panel_key
from ..models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
)
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
    build_runtime_suffix,
    render_tier_gutter,
)
from ._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _BEAD_LINKED_AGENT_GLYPH,
    _BEAD_LINKED_AGENT_GLYPH_STYLE,
    _CHILD_INDENT,
    _CLAN_NAME_STYLE,
    _FAMILY_NAME_STYLE,
    _FILE_CHANGE_GLYPH,
    _FILE_CHANGE_GLYPH_STYLE,
    _FOLD_RESTORE_GLYPH,
    _FOLD_RESTORE_GLYPH_STYLE,
    _HIDDEN_ICON,
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_FOLLOWUP_DEGRADED_OUTCOME,
    _MONITOR_FOLLOWUP_ERROR_GLYPH,
    _MONITOR_FOLLOWUP_ERROR_GLYPH_STYLE,
    _MONITOR_GLYPH,
    _MONITOR_GLYPH_STYLE,
    _MONITOR_ROW_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
    _MONITOR_STALLED_GLYPH,
    _MONITOR_STALLED_GLYPH_STYLE,
    _PROC_SHELL_GLYPH,
    _PROC_SHELL_GLYPH_STYLE,
    _PROC_SHELL_ID_STYLE,
    _PROC_SHELL_LANGUAGE_STYLE,
    _PROC_SHELL_PHASE_STYLE,
    _PROC_SHELL_ROW_STYLE,
    _REVERTED_GLYPH,
    _REVERTED_GLYPH_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TYPE_GLYPHS,
    _TREE_DEPTH_COLORS,
    _TREE_GUIDE,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
    monitor_status_presentation,
)
from ..wait_status_presentation import format_wait_dependency_status_counts


def _should_render_provider_badge(agent: Agent) -> bool:
    return not (agent.is_child_row and not agent.is_agent_entry)


def _has_file_change_hint(agent: Agent) -> bool:
    return agent_file_change_hint(agent)


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


def _tribe_style(
    tribe: str,
    tribe_colors: Mapping[str, str] | None,
) -> str:
    color = (
        tribe_colors.get(tribe, TRIBE_IDENTITY_FALLBACK_COLOR)
        if tribe_colors is not None
        else TRIBE_IDENTITY_FALLBACK_COLOR
    )
    return compose_tribe_identity_style(color, bold=True)


def format_agent_option(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    fold_restore_marked: bool = False,
    is_unread: bool = False,
    hint_char: str | None = None,
    tribe_label: str | None = None,
    panel_tribe: str | None = None,
    tribe_colors: Mapping[str, str] | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    wait_deps_satisfied: bool | None = None,
    wait_dependency_counts: WaitDependencyStatusCounts | None = None,
    has_unresolvable_wait_target: bool = False,
    clan_counts: ClanStatusCounts | None = None,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
    monitor_lanes: MonitorLaneCounts | None = None,
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
        _append_tree_indent(text, tree_depth, is_selected=is_selected)
        if approve_icon is not None:
            text.append(f"{approve_icon} ", style="bold #00FFFF")
        if agent.is_monitor:
            text.append(f"{_MONITOR_GLYPH} ", style=_monitor_glyph_style(agent))
        elif agent.is_workflow_step_child:
            step_glyph = _STEP_TYPE_GLYPHS.get(agent.step_type or "")
            if step_glyph is not None:
                glyph_color = _STEP_TYPE_COLORS.get(agent.step_type or "", "#FFFFFF")
                text.append(f"{step_glyph} ", style=f"bold {glyph_color}")
    elif agent.is_monitor:
        text.append(f"{_MONITOR_GLYPH} ", style=_monitor_glyph_style(agent))
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
                style=_tribe_style(tribe_label, tribe_colors),
            )

    # Status (wrapped in parentheses, parens are dim)
    display_status = agent.display_status
    row_prefix = text.plain
    status_opener = "(" if not row_prefix or row_prefix[-1].isspace() else " ("
    text.append(status_opener, style="dim")
    presentation = monitor_status_presentation(agent)
    if presentation is not None:
        style, glyph = presentation
        text.append(display_status, style=style)
        if glyph:
            text.append(f" {glyph}", style=style)
    elif agent.is_proc_shell and agent.status == "SETTLING":
        text.append(display_status, style="bold #FFAF5F")
    elif agent.status == "STARTING":
        text.append(display_status, style="bold #87D7FF")  # Sky blue
    elif agent.status == "RUNNING":
        text.append(display_status, style=f"bold {RUNNING_COLOR}")
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
    elif agent.status == PENDING_TALE_STATUS:
        text.append(display_status, style="bold #FF87AF")  # Pink
    elif agent.status == PENDING_EPIC_STATUS:
        text.append(display_status, style="bold #D787FF")  # Orchid
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
    elif agent.status == QUEUED_STATUS:
        text.append(display_status, style=f"bold {QUEUED_STATUS_COLOR}")
        position = agent.runner_slot_queue_position
        queue_size = agent.runner_slot_queue_size
        if position is not None:
            queue_label = f" #{position}"
            if queue_size is not None:
                queue_label += f"/{queue_size}"
            text.append(queue_label, style=QUEUED_STATUS_COLOR)
        wait_agent = wait_display_agent(agent)
        slot_label = ""
        if (
            wait_agent.wait_runners_explicit
            and wait_agent.wait_runners is not None
            and wait_agent.runner_slots_in_use is not None
        ):
            slot_label = f" ▶{wait_agent.runner_slots_in_use}→{wait_agent.wait_runners}"
        if wait_agent.wait_priority_explicit and wait_agent.wait_priority is not None:
            slot_label = f"{slot_label} p{wait_agent.wait_priority}"
        if slot_label:
            text.append(slot_label, style=f"dim {QUEUED_STATUS_COLOR}")
    elif agent.status == "WAITING":
        text.append(display_status, style="bold #AF87FF")  # Amethyst
        wait_agent = wait_display_agent(agent)
        count_text = format_wait_dependency_status_counts(wait_dependency_counts)
        if count_text.cell_len:
            text.append(" ")
            text.append_text(count_text)
        if has_unresolvable_wait_target and wait_agent.waiting_for:
            text.append(" ")
            text.append(
                _UNRESOLVABLE_WAIT_TARGET_GLYPH,
                style=_UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
            )
        deps_satisfied = (
            not wait_agent.waiting_for and not wait_agent.waiting_for_beads
            if wait_deps_satisfied is None
            else wait_deps_satisfied and not wait_agent.waiting_for_beads
        )
        wait_remaining = wait_remaining_seconds(agent, now=now)
        if wait_remaining is not None and wait_remaining > 0 and deps_satisfied:
            text.append(
                f" {format_compact_duration(wait_remaining)}",
                style="#AF87FF",
            )
        elif (
            (wait_agent.waiting_for or wait_agent.waiting_for_beads)
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
    if agent.is_monitor and agent.monitor_state in {"failed", "timeout", "lost"}:
        if agent.monitor_state == "timeout":
            text.append(" ⧖", style="bold #FFAF5F")
        elif agent.monitor_state == "failed" and agent.monitor_exit_code is not None:
            text.append(f" ✗ {agent.monitor_exit_code}", style="bold #FF5F5F")
    if (
        agent.is_monitor
        and agent.monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}
        and agent.monitor_exit_code is None
    ):
        # A terminal monitor whose supervisor never reported a real exit
        # code (dead on arrival, or a pre-reboot supervisor whose command
        # outcome is unknown): distinct from the "✗ <code>"/"⧖" badges
        # above, which mean the command itself ran and reported.
        text.append(f" {_MONITOR_STALLED_GLYPH}", style=_MONITOR_STALLED_GLYPH_STYLE)
    text.append(")", style="dim")
    if agent.is_monitor and (
        agent.monitor_followup_error
        or agent.monitor_followup_outcome == _MONITOR_FOLLOWUP_DEGRADED_OUTCOME
    ):
        text.append(
            f" {_MONITOR_FOLLOWUP_ERROR_GLYPH}",
            style=_MONITOR_FOLLOWUP_ERROR_GLYPH_STYLE,
        )
    if agent.is_proc_shell:
        if agent.proc_phase:
            text.append(f" · {agent.proc_phase}", style=_PROC_SHELL_PHASE_STYLE)
        if agent.proc_language:
            text.append(f" [{agent.proc_language}]", style=_PROC_SHELL_LANGUAGE_STYLE)

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
    if fold_restore_marked:
        text.append(" ")
        text.append(_FOLD_RESTORE_GLYPH, style=_FOLD_RESTORE_GLYPH_STYLE)

    if agent.is_clan_container:
        visible_clan_counts = (
            (
                clan_member_counts(agent, unread_agent_ids)
                if unread_agent_ids
                else clan_member_counts(agent)
            )
            if clan_counts is None
            else clan_counts
        )
        clan_chip = format_agent_count_chip(
            stopped=visible_clan_counts.awaiting,
            running=visible_clan_counts.running,
            queued=visible_clan_counts.queued,
            waiting=visible_clan_counts.waiting,
            failed=visible_clan_counts.failed,
            unread=visible_clan_counts.unread,
            done=visible_clan_counts.done,
        )
        if clan_chip:
            text.append(" ")
            text.append_text(clan_chip)

    is_container_row = agent.is_clan_container or is_sequential_family_container(agent)
    lanes = (
        (monitor_lane_counts(agent) if is_container_row else NO_MONITOR_LANES)
        if monitor_lanes is None
        else monitor_lanes
    )
    if lanes.running and is_container_row:
        text.append(" ")
        text.append(
            f"{_MONITOR_GLYPH}{lanes.running}", style=_MONITOR_COUNT_GLYPH_STYLE
        )
    if lanes.settled and is_container_row:
        text.append(" ")
        text.append(
            f"{_MONITOR_GLYPH}{lanes.settled}",
            style=_MONITOR_SETTLED_COUNT_GLYPH_STYLE,
        )

    # Authoritative-only: modern phase launch metadata renders immediately;
    # legacy candidates render after an O(1) confirmed-cache read warmed off
    # the event loop. Cold or missing legacy candidates render no glyph.
    if not agent.is_clan_container and agent_has_confirmed_bead(agent):
        text.append(" ")
        text.append(_BEAD_LINKED_AGENT_GLYPH, style=_BEAD_LINKED_AGENT_GLYPH_STYLE)

    # Shared trailing identity block. Grouping rows distinguish their name by
    # color; bead context stays to the left and clan tribes stay to the right.
    # Kind, name, and tribe inputs already participate in ``agent_render_key``;
    # static style changes need no cache-key input.
    identity_name_style = _AGENT_NAME_ANNOTATION_STYLE
    presented_name: str | None
    if agent.is_clan_container:
        identity_name_style = _CLAN_NAME_STYLE
        presented_name = agent.display_name
    elif agent.is_proc_shell:
        identity_name_style = _PROC_SHELL_ID_STYLE
        presented_name = agent.proc_id[:6] if agent.proc_id else agent.agent_name
    else:
        presented_name = agent.presented_agent_name or agent.agent_name
        if is_family_container_row:
            identity_name_style = _FAMILY_NAME_STYLE

    if presented_name:
        text.append(" ")
        text.append(presented_name, style=identity_name_style)

    if agent.is_clan_container:
        rendered_tribes = tuple(
            dict.fromkeys(
                tribe
                for tribe in agent.clan_tribes
                if normalize_panel_key(tribe) != normalize_panel_key(panel_tribe)
            )
        )
        for clan_tribe in rendered_tribes:
            text.append(
                f" @{clan_tribe}",
                style=_tribe_style(clan_tribe, tribe_colors),
            )
        if tribe_label and tribe_label not in rendered_tribes:
            text.append(
                f" @{tribe_label}",
                style=_tribe_style(tribe_label, tribe_colors),
            )

    # Embedded workflow annotation for child steps
    if agent.embedded_workflow_name:
        text.append(" ", style="")
        if agent.is_pre_prompt_step:
            text.append("▲", style="bold #5F87AF")
        else:
            text.append("▼", style="bold #D7AF5F")
        text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

    node_unread = is_unread and is_agents_tab_agent_node(agent)
    runtime_suffix = build_runtime_suffix(agent, now=now, is_unread=node_unread)
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

    suffix = runtime_with_file_change
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
    fold_restore_marked: bool = False,
    is_unread: bool = False,
    hint_char: str | None = None,
    tribe_label: str | None = None,
    panel_tribe: str | None = None,
    tribe_colors: Mapping[str, str] | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    wait_deps_satisfied: bool | None = None,
    wait_dependency_counts: WaitDependencyStatusCounts | None = None,
    has_unresolvable_wait_target: bool = False,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> tuple[Text, Text, str]:
    """Memoized wrapper for :func:`format_agent_option`.

    Reuses ``(left, suffix, option_id)`` from *cache* when every input
    matches a prior call. ``Text`` objects from Rich are immutable for
    our purposes (we don't mutate them after assemble); returning the
    cached object avoids rebuilding an O(rows) Text tree on each refresh.
    """
    visible_clan_counts = (
        (
            clan_member_counts(agent, unread_agent_ids)
            if unread_agent_ids
            else clan_member_counts(agent)
        )
        if agent.is_clan_container
        else None
    )
    is_container_row = agent.is_clan_container or is_sequential_family_container(agent)
    lanes = monitor_lane_counts(agent) if is_container_row else NO_MONITOR_LANES
    key = agent_render_key(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        fold_restore_marked=fold_restore_marked,
        is_unread=is_unread,
        hint_char=hint_char,
        tribe_label=tribe_label,
        panel_tribe=panel_tribe,
        tribe_colors=tribe_colors,
        now=now,
        tier_styles=tier_styles,
        wait_deps_satisfied=wait_deps_satisfied,
        wait_dependency_counts=wait_dependency_counts,
        has_unresolvable_wait_target=has_unresolvable_wait_target,
        clan_counts=visible_clan_counts,
        unread_agent_ids=unread_agent_ids,
        monitor_lanes=lanes,
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
        fold_restore_marked=fold_restore_marked,
        is_unread=is_unread,
        hint_char=hint_char,
        tribe_label=tribe_label,
        panel_tribe=panel_tribe,
        tribe_colors=tribe_colors,
        now=now,
        tier_styles=tier_styles,
        wait_deps_satisfied=wait_deps_satisfied,
        wait_dependency_counts=wait_dependency_counts,
        has_unresolvable_wait_target=has_unresolvable_wait_target,
        clan_counts=visible_clan_counts,
        unread_agent_ids=unread_agent_ids,
        monitor_lanes=lanes,
    )
    cache.put_agent(key, parts)
    return parts
