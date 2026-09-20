"""Row-building blocks shared by the AgentList rebuild and in-place insert.

``build_list`` (full rebuild) and ``try_insert_rows`` (in-place insert) must
agree on how an agent row is formatted and where the grouping tree puts it,
otherwise an inserted row would differ from the one a rebuild would emit. Both
call the helpers here so that agreement is structural rather than a matter of
keeping two copies in step.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from ..agent_completion import (
    AgentWaitStatusMaps,
    agent_wait_status_maps_for_app,
    collect_agent_wait_status_maps,
    has_unresolvable_wait_target,
    wait_dependency_status_counts,
    wait_dependencies_satisfied,
)
from ..models._agent_tree import agent_fold_key, agent_is_tree_child
from ..models.agent import Agent, AgentType
from ..models.agent_groups import GroupingMode, GroupRow, TreeEntry
from ..models.agent_nodes import is_agents_tab_agent_node
from ..models.agent_wait_beads import cached_wait_bead_status_snapshot
from ..models.tribe_display import named_tribe_identity_colors
from ._agent_list_build_analysis import compute_visible_parents
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    AgentRenderCache,
    BannerMarkState,
    cached_format_agent_option,
    cached_format_banner_option,
)
from ._agent_list_styling import _BANNER_ROW

AgentIdentity = tuple[AgentType, str, str | None]

# Padding added around the widest emitted row when requesting panel width.
_WIDTH_PADDING = 8


@dataclass(frozen=True)
class _RowInputs:
    """Panel-wide inputs that decide how every agent row of one panel is built."""

    current_idx: int
    current_group_key: tuple[str, ...] | None
    marked: set[AgentIdentity]
    unread: set[AgentIdentity]
    restore_marked_keys: Collection[str]
    fold_counts: dict[str, tuple[int, int]] | None
    jump_hints: dict[int, str] | None
    tribe_labels: list[str | None] | None
    panel_tribe: str | None
    tribe_colors: dict[str, str]
    parents_with_visible_children: set[str]
    fully_expanded_parents: set[str]
    show_machine_chip: bool
    wait_status_maps: AgentWaitStatusMaps
    now: datetime | None


def _agent_row_chrome_mode(agents: list[Agent]) -> bool:
    """Return whether machine chips are enabled for this list.

    Chips turn on whenever any loaded row has a fleet origin, including
    under ``BY_MACHINE`` group headers. Local rows and indented member
    shells still render none; only rows with ``fleet_origin_alias`` do.
    """
    return any(getattr(agent, "fleet_origin_alias", None) for agent in agents)


def _agent_wait_status_maps_for_build(
    widget: Any,
    agents: list[Agent],
) -> AgentWaitStatusMaps:
    """Return wait state from the app's full loaded snapshot when available."""
    try:
        app = getattr(widget, "app", None)
    except Exception:
        app = None
    return agent_wait_status_maps_for_app(app) or collect_agent_wait_status_maps(agents)


def build_row_inputs(
    widget: Any,
    agents: list[Agent],
    current_idx: int,
    *,
    marked_agents: set[AgentIdentity] | None,
    unread_agents: set[AgentIdentity] | None,
    fold_restore_marked_keys: Collection[str] | None,
    fold_counts: dict[str, tuple[int, int]] | None,
    jump_hints: dict[int, str] | None,
    current_group_key: tuple[str, ...] | None,
    tribe_labels: list[str | None] | None,
    panel_tribe: str | None,
    parents_with_visible_children: set[str] | None,
    fully_expanded_parents: set[str] | None,
    now: datetime | None,
) -> _RowInputs:
    """Collect the panel-wide inputs for one build of *agents*."""
    semantic_tribes = {tribe for agent in agents for tribe in agent.clan_tribes}
    if tribe_labels is not None:
        semantic_tribes.update(tribe for tribe in tribe_labels if tribe is not None)
    if parents_with_visible_children is None or fully_expanded_parents is None:
        local_visible_parents, local_fully_expanded = compute_visible_parents(agents)
        if parents_with_visible_children is None:
            parents_with_visible_children = local_visible_parents
        if fully_expanded_parents is None:
            fully_expanded_parents = local_fully_expanded
    return _RowInputs(
        current_idx=current_idx,
        current_group_key=current_group_key,
        marked=marked_agents or set(),
        unread=unread_agents or set(),
        restore_marked_keys=fold_restore_marked_keys or (),
        fold_counts=fold_counts,
        jump_hints=jump_hints,
        tribe_labels=tribe_labels,
        panel_tribe=panel_tribe,
        tribe_colors=named_tribe_identity_colors(semantic_tribes),
        parents_with_visible_children=parents_with_visible_children,
        fully_expanded_parents=fully_expanded_parents,
        show_machine_chip=_agent_row_chrome_mode(agents),
        wait_status_maps=_agent_wait_status_maps_for_build(widget, agents),
        now=now,
    )


def agent_row_context(inputs: _RowInputs, agent: Agent, index: int) -> dict[str, Any]:
    """Return the render context for ``agents[index]``'s row.

    The dict is what ``AgentList._row_render_ctx`` stores per row, so
    ``patch_row`` can re-emit the row later with the same inputs.
    """
    fold_key = agent_fold_key(agent)
    is_expanded = bool(
        fold_key is not None and fold_key in inputs.parents_with_visible_children
    )
    tribe_labels = inputs.tribe_labels
    wait_status_maps = inputs.wait_status_maps
    return {
        "fold_annotation": compute_fold_annotation(
            agent,
            inputs.fold_counts,
            inputs.parents_with_visible_children,
            inputs.fully_expanded_parents,
        ),
        "is_expanded": is_expanded,
        "is_marked": agent.identity in inputs.marked,
        "fold_restore_marked": bool(
            fold_key and fold_key in inputs.restore_marked_keys
        ),
        "is_unread": agent.identity in inputs.unread
        and is_agents_tab_agent_node(agent),
        "hint_char": (inputs.jump_hints or {}).get(index),
        "tribe_label": (
            tribe_labels[index]
            if tribe_labels is not None and index < len(tribe_labels)
            else None
        ),
        "panel_tribe": inputs.panel_tribe,
        "tribe_colors": inputs.tribe_colors,
        "is_selected": inputs.current_group_key is None and index == inputs.current_idx,
        "wait_deps_satisfied": wait_dependencies_satisfied(
            agent,
            wait_status_maps.buckets,
            wait_status_maps.tribe_bindings,
        ),
        "wait_dependency_counts": wait_dependency_status_counts(
            agent,
            wait_status_maps,
            cached_wait_bead_status_snapshot(agent),
        ),
        "has_unresolvable_wait_target": has_unresolvable_wait_target(
            agent,
            wait_status_maps.tribe_bindings,
        ),
        "show_machine_chip": inputs.show_machine_chip,
    }


def format_agent_row(
    cache: AgentRenderCache,
    inputs: _RowInputs,
    agent: Agent,
    index: int,
    ctx: Mapping[str, Any],
    tier_styles: tuple[str, ...],
) -> tuple[Text, Text, str]:
    """Format one agent row as ``(left, suffix, option_id)`` from its context."""
    return cached_format_agent_option(
        cache,
        agent,
        index,
        is_selected=ctx["is_selected"],
        fold_annotation=ctx["fold_annotation"],
        is_expanded=ctx["is_expanded"],
        is_marked=ctx["is_marked"],
        fold_restore_marked=ctx["fold_restore_marked"],
        is_unread=ctx["is_unread"],
        hint_char=ctx["hint_char"],
        tribe_label=ctx["tribe_label"],
        panel_tribe=ctx["panel_tribe"],
        tribe_colors=ctx["tribe_colors"],
        now=inputs.now,
        tier_styles=tier_styles,
        wait_deps_satisfied=ctx["wait_deps_satisfied"],
        wait_dependency_counts=ctx["wait_dependency_counts"],
        has_unresolvable_wait_target=ctx["has_unresolvable_wait_target"],
        unread_agent_ids=inputs.unread,
        show_machine_chip=ctx["show_machine_chip"],
    )


def _banner_mark_state(
    group: GroupRow,
    agents: list[Agent],
    marked: set[AgentIdentity],
) -> BannerMarkState:
    """Classify top-level group members as unmarked, partially, or all marked."""
    member_identities = [
        agents[idx].identity
        for idx in group.agent_indices
        if 0 <= idx < len(agents) and not agent_is_tree_child(agents[idx])
    ]
    if not member_identities:
        return "none"
    marked_count = sum(1 for identity in member_identities if identity in marked)
    if marked_count == 0:
        return "none"
    if marked_count == len(member_identities):
        return "all"
    return "partial"


@dataclass
class _TreeRows:
    """The options a grouping tree emits, plus the per-row trackers for them."""

    options: list[Option]
    row_entries: list[tuple[int, int | None]]
    banner_at_row: dict[int, GroupRow]
    banner_row_by_key: dict[tuple[str, ...], int]
    row_by_agent_attempt: dict[tuple[int, int | None], int]
    row_by_agent_idx: dict[int, int]
    highlighted_row: int | None
    # Widest banner, floored at the agent-row alignment width.
    max_emitted_width: int


def emit_tree_rows(
    tree: list[TreeEntry],
    agents: list[Agent],
    *,
    agent_options: Mapping[int, Option],
    cache: AgentRenderCache,
    target_width: int,
    banner_tier_styles: list[tuple[str, ...]],
    banner_jump_hints: dict[tuple[str, ...], str] | None,
    grouping_mode: GroupingMode,
    marked: set[AgentIdentity],
    current_idx: int,
    current_group_key: tuple[str, ...] | None,
) -> _TreeRows:
    """Walk *tree* and collect Options and row trackers in display order.

    Banners pad to *target_width*, the widest emitted agent row, so their
    chips line up with the runtime-suffix column.
    """
    rows = _TreeRows(
        options=[],
        row_entries=[],
        banner_at_row={},
        banner_row_by_key={},
        row_by_agent_attempt={},
        row_by_agent_idx={},
        highlighted_row=None,
        max_emitted_width=target_width,
    )
    banner_seq = 0
    spacer_seq = 0
    seen_first_l0 = False
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            if entry.group.level == 0:
                if seen_first_l0:
                    rows.options.append(
                        Option(Text(""), id=f"spacer:{spacer_seq}", disabled=True)
                    )
                    spacer_seq += 1
                    rows.row_entries.append((_BANNER_ROW, None))
                seen_first_l0 = True
            banner_selectable = entry.group.is_collapsed
            tier_styles_for_banner = (
                banner_tier_styles[banner_seq]
                if banner_seq < len(banner_tier_styles)
                else ()
            )
            banner_hint = (banner_jump_hints or {}).get(entry.group.group_key)
            mark_state = (
                _banner_mark_state(entry.group, agents, marked)
                if banner_selectable
                else "none"
            )
            banner_option = cached_format_banner_option(
                cache,
                entry.group,
                agents,
                width=target_width,
                sequence=banner_seq,
                selectable=banner_selectable,
                mode=grouping_mode,
                tier_styles=tier_styles_for_banner,
                hint_char=banner_hint,
                mark_state=mark_state,
            )
            prompt = banner_option.prompt
            if isinstance(prompt, Text):
                rows.max_emitted_width = max(rows.max_emitted_width, prompt.cell_len)
            banner_seq += 1
            row_index = len(rows.row_entries)
            rows.options.append(banner_option)
            rows.row_entries.append((_BANNER_ROW, None))
            if banner_selectable:
                rows.banner_at_row[row_index] = entry.group
                rows.banner_row_by_key[entry.group.group_key] = row_index
                if (
                    current_group_key is not None
                    and entry.group.group_key == current_group_key
                    and rows.highlighted_row is None
                ):
                    rows.highlighted_row = row_index
            continue

        if entry.agent_idx is None:
            continue
        i = entry.agent_idx
        agent_option = agent_options.get(i)
        if agent_option is None:
            continue
        rows.options.append(agent_option)
        row_index = len(rows.row_entries)
        if current_group_key is None and i == current_idx:
            rows.highlighted_row = row_index
        rows.row_entries.append((i, None))
        rows.row_by_agent_attempt[(i, None)] = row_index
        rows.row_by_agent_idx[i] = row_index
    return rows


def requested_panel_width(rows: _TreeRows) -> int:
    """Return the panel width to request for the emitted *rows*."""
    return rows.max_emitted_width + _WIDTH_PADDING


__all__ = [
    "agent_row_context",
    "build_row_inputs",
    "emit_tree_rows",
    "format_agent_row",
    "requested_panel_width",
]
