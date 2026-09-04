"""Agent row rendering — builds the ``(left, suffix, option_id)`` parts
for one agent in the list, plus a memoized wrapper backed by
:class:`AgentRenderCache`.

Leading chrome and the status parenthetical live in
``_agent_list_render_agent_prefix`` and ``_agent_list_render_agent_status``.
"""

from collections.abc import Collection, Mapping
from datetime import datetime

from rich.text import Text

from ..agent_completion import WaitDependencyStatusCounts
from ..agent_count_chip import format_agent_count_chip
from ..models._agent_clan import ClanStatusCounts, clan_member_counts
from ..models.agent import Agent, AgentType
from ..models.agent_bead import agent_has_confirmed_bead
from ..models.agent_family_members import (
    NO_SHELL_LANES,
    ShellLaneCounts,
    is_sequential_family_container,
    shell_lane_counts,
)
from ..models.agent_nodes import is_agents_tab_agent_node
from ..models.agent_panels import normalize_panel_key
from ._agent_list_render_agent_prefix import (
    append_agent_row_prefix,
    tribe_style,
)
from ._agent_list_render_agent_status import append_agent_row_status
from ._agent_list_render_cache import (
    AgentRenderCache,
    agent_file_change_hint,
    agent_render_key,
)
from ._agent_list_render_layout import build_runtime_suffix
from ._owner_badge import append_owner_badge
from ._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _BEAD_LINKED_AGENT_GLYPH,
    _BEAD_LINKED_AGENT_GLYPH_STYLE,
    _CLAN_NAME_STYLE,
    _FAMILY_NAME_STYLE,
    _FILE_CHANGE_GLYPH,
    _FILE_CHANGE_GLYPH_STYLE,
    _FOLD_RESTORE_GLYPH,
    _FOLD_RESTORE_GLYPH_STYLE,
    _GATE_COUNT_GLYPH_STYLE,
    _GATE_FAILED_COUNT_GLYPH_STYLE,
    _GATE_GLYPH,
    _GATE_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_GLYPH,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
    _PROC_SHELL_ID_STYLE,
)


def _has_file_change_hint(agent: Agent) -> bool:
    return agent_file_change_hint(agent)


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
    shell_lanes: ShellLaneCounts | None = None,
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for an agent row."""
    text = append_agent_row_prefix(
        agent,
        is_selected=is_selected,
        is_expanded=is_expanded,
        is_marked=is_marked,
        hint_char=hint_char,
        tribe_label=tribe_label,
        tribe_colors=tribe_colors,
        tier_styles=tier_styles,
    )
    append_agent_row_status(
        text,
        agent,
        now=now,
        wait_deps_satisfied=wait_deps_satisfied,
        wait_dependency_counts=wait_dependency_counts,
        has_unresolvable_wait_target=has_unresolvable_wait_target,
    )
    is_family_container_row = agent.is_family_container_row

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
        (shell_lane_counts(agent) if is_container_row else NO_SHELL_LANES)
        if shell_lanes is None
        else shell_lanes
    )
    if lanes.monitor.running and is_container_row:
        text.append(" ")
        text.append(
            f"{_MONITOR_GLYPH}{lanes.monitor.running}",
            style=_MONITOR_COUNT_GLYPH_STYLE,
        )
    if lanes.monitor.settled and is_container_row:
        text.append(" ")
        text.append(
            f"{_MONITOR_GLYPH}{lanes.monitor.settled}",
            style=_MONITOR_SETTLED_COUNT_GLYPH_STYLE,
        )
    if lanes.gate.running and is_container_row:
        text.append(" ")
        text.append(f"{_GATE_GLYPH}{lanes.gate.running}", style=_GATE_COUNT_GLYPH_STYLE)
    if lanes.gate.settled and is_container_row:
        text.append(" ")
        text.append(
            f"{_GATE_GLYPH}{lanes.gate.settled}",
            style=_GATE_SETTLED_COUNT_GLYPH_STYLE,
        )
    if lanes.gate.failed and is_container_row:
        text.append(" ")
        text.append(
            f"{_GATE_GLYPH}{lanes.gate.failed}",
            style=_GATE_FAILED_COUNT_GLYPH_STYLE,
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
        presented_name = f"[{agent.proc_language}]" if agent.proc_language else None
    else:
        presented_name = agent.presented_agent_name or agent.agent_name
        if is_family_container_row:
            identity_name_style = _FAMILY_NAME_STYLE

    if presented_name:
        text.append(" ")
        text.append(presented_name, style=identity_name_style)
        append_owner_badge(text, agent)

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
                style=tribe_style(clan_tribe, tribe_colors),
            )
        if tribe_label and tribe_label not in rendered_tribes:
            text.append(
                f" @{tribe_label}",
                style=tribe_style(tribe_label, tribe_colors),
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
    lanes = shell_lane_counts(agent) if is_container_row else NO_SHELL_LANES
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
        shell_lanes=lanes,
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
        shell_lanes=lanes,
    )
    cache.put_agent(key, parts)
    return parts
