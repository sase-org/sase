"""Full AgentList rebuild helper."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any

from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from ..models.agent_groups import GroupingMode, TreeEntry, build_agent_tree
from ..models.group_fold import GroupFoldView
from ._agent_list_build_analysis import (
    compute_tier_styles,
    visible_agent_indices,
)
from ._agent_list_build_rows import (
    agent_row_context,
    build_row_inputs,
    emit_tree_rows,
    format_agent_row,
    requested_panel_width,
)
from ._agent_list_rendering import assemble_padded_option
from ._agent_list_styling import _MIN_BANNER_WIDTH


# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports the
# build facade), and pyright infers ``Self@AgentList`` as a distinct type
# from the imported alias when ``Self`` flows through subclass-bound
# calls. ``Any`` keeps the helpers self-contained while the widget API
# stays strongly typed in ``agent_list.py``.


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

    inputs = build_row_inputs(
        widget,
        agents,
        current_idx,
        marked_agents=marked_agents,
        unread_agents=unread_agents,
        fold_restore_marked_keys=fold_restore_marked_keys,
        fold_counts=fold_counts,
        jump_hints=jump_hints,
        current_group_key=current_group_key,
        tribe_labels=tribe_labels,
        panel_tribe=panel_tribe,
        parents_with_visible_children=parents_with_visible_children,
        fully_expanded_parents=fully_expanded_parents,
        now=now,
    )
    widget._unread_agents = set(inputs.unread)
    widget._tribe_identity_colors = inputs.tribe_colors

    widget._grouping_mode = grouping_mode
    tree: list[TreeEntry] = build_agent_tree(
        agents, fold_registry=fold_registry, mode=grouping_mode, now=now
    )
    panel_uses_cs = grouping_mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    agent_tier_styles, banner_tier_styles = compute_tier_styles(
        tree, panel_uses_cs=panel_uses_cs, mode=grouping_mode
    )
    visible = visible_agent_indices(tree)

    # Measure what you emit: format only the agent rows the tree will
    # actually paint. Collapsed-group members are skipped so they don't
    # stretch max_left / max_suffix or populate per-row render state.
    # Banners pad to the widest *emitted* row; the runtime suffix is
    # right-aligned to that same column.
    agent_parts: dict[int, tuple[Any, Any, str]] = {}
    max_left = 0
    max_suffix = 0
    for i, agent in enumerate(agents):
        if i not in visible:
            continue
        ctx = agent_row_context(inputs, agent, i)
        tier_styles = agent_tier_styles.get(i, ())
        left, suffix, option_id = format_agent_row(
            widget._agent_render_cache, inputs, agent, i, ctx, tier_styles
        )
        agent_parts[i] = (left, suffix, option_id)
        widget._row_render_ctx[i] = ctx
        widget._row_tier_styles[i] = tier_styles
        max_left = max(max_left, left.cell_len)
        max_suffix = max(max_suffix, suffix.cell_len)

    gap = 2 if max_suffix > 0 else 0
    target_width = max(_MIN_BANNER_WIDTH, max_left + gap + max_suffix)
    widget._target_width = target_width
    widget._max_left = max_left
    widget._max_suffix = max_suffix

    agent_options: dict[int, Option] = {
        i: assemble_padded_option(left, suffix, width=target_width, option_id=option_id)
        for i, (left, suffix, option_id) in agent_parts.items()
    }

    # Walk the grouping tree and collect Options in display order. Installing
    # them as one batch avoids Textual rebuilding its line cache per row.
    rows = emit_tree_rows(
        tree,
        agents,
        agent_options=agent_options,
        cache=widget._agent_render_cache,
        target_width=target_width,
        banner_tier_styles=banner_tier_styles,
        banner_jump_hints=banner_jump_hints,
        grouping_mode=grouping_mode,
        marked=inputs.marked,
        current_idx=current_idx,
        current_group_key=current_group_key,
    )
    widget._row_entries = rows.row_entries
    widget._banner_at_row = rows.banner_at_row
    widget._banner_row_by_key = rows.banner_row_by_key
    widget._row_by_agent_attempt = rows.row_by_agent_attempt
    widget._row_by_agent_idx = rows.row_by_agent_idx

    widget.add_options(rows.options)

    # Widest emitted row (visible agent column or banner) plus padding.
    # Banners are measured from the Option already built so this cannot
    # drift from the formatter.
    widget._content_requested_width = requested_panel_width(rows)
    widget._refresh_requested_width()

    try:
        if rows.highlighted_row is not None:
            widget._set_highlighted_programmatically(rows.highlighted_row)
    finally:
        widget._programmatic_update = False


__all__ = ["build_list"]
