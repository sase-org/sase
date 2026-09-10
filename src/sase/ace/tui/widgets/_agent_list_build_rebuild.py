"""Full AgentList rebuild helper."""

from __future__ import annotations

from collections.abc import Collection
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
from ..models.agent_groups import GroupingMode, GroupRow, TreeEntry, build_agent_tree
from ..models.agent_nodes import is_agents_tab_agent_node
from ..models.agent_wait_beads import cached_wait_bead_status_snapshot
from ..models.group_fold import GroupFoldView
from ..models.tribe_display import named_tribe_identity_colors
from ._agent_list_build_analysis import compute_tier_styles, compute_visible_parents
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    BannerMarkState,
    assemble_padded_option,
    cached_format_agent_option,
    cached_format_banner_option,
)
from ._agent_list_styling import _BANNER_ROW, _MIN_BANNER_WIDTH


# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports the
# build facade), and pyright infers ``Self@AgentList`` as a distinct type
# from the imported alias when ``Self`` flows through subclass-bound
# calls. ``Any`` keeps the helpers self-contained while the widget API
# stays strongly typed in ``agent_list.py``.


def _banner_mark_state(
    group: GroupRow,
    agents: list[Agent],
    marked: set[tuple[AgentType, str, str | None]],
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


def _agent_row_chrome_mode(
    agents: list[Agent],
    grouping_mode: GroupingMode,
) -> tuple[bool, bool]:
    """Return ``(show_machine_chip, show_fleet_badge)`` for agent rows."""
    if grouping_mode is GroupingMode.BY_MACHINE:
        return False, False
    return any(getattr(agent, "fleet_origin_alias", None) for agent in agents), False


def build_list(
    widget: Any,
    agents: list[Agent],
    current_idx: int,
    *,
    fold_counts: dict[str, tuple[int, int]] | None = None,
    marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
    unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
    fold_restore_marked_keys: Collection[str] | None = None,
    jump_hints: dict[int, str] | None = None,
    banner_jump_hints: dict[tuple[str, ...], str] | None = None,
    fold_registry: GroupFoldView | None = None,
    current_group_key: tuple[str, ...] | None = None,
    grouping_mode: GroupingMode = GroupingMode.STANDARD,
    tribe_labels: list[str | None] | None = None,
    panel_tribe: str | None = None,
    parents_with_visible_children: set[str] | None = None,
    fully_expanded_parents: set[str] | None = None,
    now: datetime | None = None,
) -> None:
    """Rebuild *widget*'s OptionList from scratch for ``agents``.

    Mutates the widget's per-row state maps (``_row_entries``,
    ``_row_render_ctx``, etc.) and posts a :class:`WidthChanged`
    message so the container can resize.
    """
    widget._programmatic_update = True
    widget._panel_collapsed = False
    widget._agents = agents
    widget.clear_options()
    widget._row_entries = []
    widget._banner_at_row = {}
    widget._row_render_ctx = {}
    widget._row_tier_styles = {}
    widget._row_by_agent_attempt = {}
    widget._row_by_agent_idx = {}
    widget._banner_row_by_key = {}

    marked = marked_agents or set()
    unread = unread_agents or set()
    restore_marked_keys = fold_restore_marked_keys or ()
    widget._unread_agents = set(unread)
    semantic_tribes = {tribe for agent in agents for tribe in agent.clan_tribes}
    if tribe_labels is not None:
        semantic_tribes.update(tribe for tribe in tribe_labels if tribe is not None)
    tribe_colors = named_tribe_identity_colors(semantic_tribes)
    widget._tribe_identity_colors = tribe_colors
    if parents_with_visible_children is None or fully_expanded_parents is None:
        local_visible_parents, local_fully_expanded = compute_visible_parents(agents)
        if parents_with_visible_children is None:
            parents_with_visible_children = local_visible_parents
        if fully_expanded_parents is None:
            fully_expanded_parents = local_fully_expanded

    widget._grouping_mode = grouping_mode
    show_machine_chip, show_fleet_badge = _agent_row_chrome_mode(
        agents,
        grouping_mode,
    )
    tree: list[TreeEntry] = build_agent_tree(
        agents, fold_registry=fold_registry, mode=grouping_mode, now=now
    )
    panel_uses_cs = grouping_mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    agent_tier_styles, banner_tier_styles = compute_tier_styles(
        tree, panel_uses_cs=panel_uses_cs, mode=grouping_mode
    )
    wait_status_maps = _agent_wait_status_maps_for_build(widget, agents)
    status_buckets = wait_status_maps.buckets

    # Pre-format agent rows so we know their widths before emitting banner
    # rules (banners are stretched to the widest row, and the runtime
    # suffix is right-aligned to the same column).
    agent_parts: dict[int, tuple[Any, Any, str]] = {}
    max_left = 0
    max_suffix = 0
    for i, agent in enumerate(agents):
        fold_key = agent_fold_key(agent)
        is_expanded = bool(
            fold_key is not None and fold_key in parents_with_visible_children
        )
        is_marked = agent.identity in marked
        is_unread = agent.identity in unread and is_agents_tab_agent_node(agent)
        restore_marked = bool(fold_key and fold_key in restore_marked_keys)
        annotation = compute_fold_annotation(
            agent,
            fold_counts,
            parents_with_visible_children,
            fully_expanded_parents,
        )
        is_selected_agent = current_group_key is None and i == current_idx
        hint = (jump_hints or {}).get(i)
        tribe_label = (
            tribe_labels[i]
            if tribe_labels is not None and i < len(tribe_labels)
            else None
        )
        tier_styles = agent_tier_styles.get(i, ())
        wait_deps_done = wait_dependencies_satisfied(
            agent,
            status_buckets,
            wait_status_maps.tribe_bindings,
        )
        wait_counts = wait_dependency_status_counts(
            agent,
            wait_status_maps,
            cached_wait_bead_status_snapshot(agent),
        )
        has_unresolvable_wait = has_unresolvable_wait_target(
            agent,
            wait_status_maps.tribe_bindings,
        )
        left, suffix, option_id = cached_format_agent_option(
            widget._agent_render_cache,
            agent,
            i,
            is_selected=is_selected_agent,
            fold_annotation=annotation,
            is_expanded=is_expanded,
            is_marked=is_marked,
            fold_restore_marked=restore_marked,
            is_unread=is_unread,
            hint_char=hint,
            tribe_label=tribe_label,
            panel_tribe=panel_tribe,
            tribe_colors=tribe_colors,
            now=now,
            tier_styles=tier_styles,
            wait_deps_satisfied=wait_deps_done,
            wait_dependency_counts=wait_counts,
            has_unresolvable_wait_target=has_unresolvable_wait,
            unread_agent_ids=unread,
            show_machine_chip=show_machine_chip,
            show_fleet_badge=show_fleet_badge,
        )
        agent_parts[i] = (left, suffix, option_id)
        widget._row_render_ctx[i] = {
            "fold_annotation": annotation,
            "is_expanded": is_expanded,
            "is_marked": is_marked,
            "fold_restore_marked": restore_marked,
            "is_unread": is_unread,
            "hint_char": hint,
            "tribe_label": tribe_label,
            "panel_tribe": panel_tribe,
            "tribe_colors": tribe_colors,
            "is_selected": is_selected_agent,
            "wait_deps_satisfied": wait_deps_done,
            "wait_dependency_counts": wait_counts,
            "has_unresolvable_wait_target": has_unresolvable_wait,
            "show_machine_chip": show_machine_chip,
            "show_fleet_badge": show_fleet_badge,
        }
        widget._row_tier_styles[i] = tier_styles
        max_left = max(max_left, left.cell_len)
        max_suffix = max(max_suffix, suffix.cell_len)

    gap = 2 if max_suffix > 0 else 0
    target_width = max(_MIN_BANNER_WIDTH, max_left + gap + max_suffix)
    banner_width = target_width
    widget._target_width = target_width

    agent_options: dict[int, Option] = {
        i: assemble_padded_option(left, suffix, width=target_width, option_id=option_id)
        for i, (left, suffix, option_id) in agent_parts.items()
    }
    max_width = target_width

    # Walk the grouping tree and collect Options in display order. Installing
    # them as one batch avoids Textual rebuilding its line cache per row.
    emitted_options: list[Option] = []
    highlighted_row: int | None = None
    banner_seq = 0
    spacer_seq = 0
    seen_first_l0 = False
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            if entry.group.level == 0:
                if seen_first_l0:
                    spacer = Option(
                        Text(""),
                        id=f"spacer:{spacer_seq}",
                        disabled=True,
                    )
                    spacer_seq += 1
                    emitted_options.append(spacer)
                    widget._row_entries.append((_BANNER_ROW, None))
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
            option = cached_format_banner_option(
                widget._agent_render_cache,
                entry.group,
                widget._agents,
                width=banner_width,
                sequence=banner_seq,
                selectable=banner_selectable,
                mode=grouping_mode,
                tier_styles=tier_styles_for_banner,
                hint_char=banner_hint,
                mark_state=mark_state,
            )
            banner_seq += 1
            row_index = len(widget._row_entries)
            emitted_options.append(option)
            widget._row_entries.append((_BANNER_ROW, None))
            if banner_selectable:
                widget._banner_at_row[row_index] = entry.group
                widget._banner_row_by_key[entry.group.group_key] = row_index
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
        option = agent_options[i]
        emitted_options.append(option)
        is_selected_agent = current_group_key is None and i == current_idx
        row_index = len(widget._row_entries)
        if is_selected_agent:
            highlighted_row = row_index
        widget._row_entries.append((i, None))
        widget._row_by_agent_attempt[(i, None)] = row_index
        widget._row_by_agent_idx[i] = row_index

    widget.add_options(emitted_options)

    # Add padding for border, scrollbar, visual comfort (~8 cells)
    _PADDING = 8
    optimal_width = max(max_width, banner_width) + _PADDING
    widget._content_requested_width = optimal_width
    widget._refresh_requested_width()

    try:
        if highlighted_row is not None:
            widget._set_highlighted_programmatically(highlighted_row)
    finally:
        widget._programmatic_update = False


__all__ = ["build_list"]
