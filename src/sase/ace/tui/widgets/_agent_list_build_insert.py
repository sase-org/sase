"""In-place row insertion for AgentList.

Part of the ``_agent_list_build_patching`` split: :func:`try_insert_rows`
and its private gates. Only public names cross module boundaries here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from textual.widgets.option_list import DuplicateID, Option

from ..models.agent import Agent, AgentType
from ..models.agent_groups import (
    GroupingMode,
    build_agent_tree,
)
from ..models.group_fold import GroupFoldView, group_fold_snapshot
from ._agent_list_build_analysis import compute_tier_styles, visible_agent_indices
from ._agent_list_build_rows import (
    agent_row_context,
    build_row_inputs,
    emit_tree_rows,
    format_agent_row,
    requested_panel_width,
    suppress_lone_machine_banner,
    widget_app_or_none,
)
from ._agent_list_rendering import (
    agent_option_id,
    assemble_padded_option,
)
from ._agent_list_styling import BANNER_ROW


# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports the
# build facade). ``Any`` keeps the helpers self-contained while the
# widget API stays strongly typed in ``agent_list.py``.


# Grouping modes whose tree the in-place paths know how to mirror.
_INPLACE_GROUPING_MODES = frozenset(
    {GroupingMode.STANDARD, GroupingMode.BY_STATUS, GroupingMode.BY_MACHINE}
)


def _decline_insert(widget: Any, reason: str | None) -> bool:
    """Record why ``try_insert_rows`` did not apply and return ``False``.

    *reason* is one of the ``AgentRefreshFallbackReason`` names, or ``None``
    when the panel simply is not an insert candidate (nothing to insert into,
    or nothing was added), which is not a fallback worth reporting.
    """
    widget._insert_decline_reason = reason
    return False


def _is_plain_leaf_row(agent: Agent) -> bool:
    """Whether *agent* renders as one standalone row that owns no descendants.

    Clan containers and members, session containers, and workflow parents and
    steps change a synthetic container row or a descendant topology that only
    a rebuild reprojects, so they are never inserted in place.
    """
    return not (
        agent.is_clan_container
        or agent.agent_clan
        or agent.is_agent_session_container_row
        or agent.is_imported_agent_session_container
        or agent.agent_type is AgentType.WORKFLOW
        or agent.is_child_row
        or agent.tree_parent_key
        or agent.tree_depth > 0
        or agent.parent_timestamp is not None
        or agent.parent_workflow is not None
    )


def _same_row_context(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    """Whether two row contexts would paint the same row.

    ``is_selected`` is skipped: j/k moves the highlight without repainting rows,
    so a painted row's emphasis already lags the selection until its next
    patch or rebuild, and an insert must not repaint every row to fix that.
    """
    return all(
        old.get(key) == value for key, value in new.items() if key != "is_selected"
    )


def _with_option_id(option: Option, option_id: str) -> Option:
    """Return *option* if it already has *option_id*, else a copy that does."""
    if option.id == option_id:
        return option
    return Option(option.prompt, id=option_id, disabled=option.disabled)


def try_insert_rows(
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
) -> bool:
    """Insert rows that joined *agents* in place; return ``True`` on success.

    The mirror of ``try_remove_rows``. *agents* is the panel's full new
    list; the widget's current list must be an ordered subsequence of it, so
    every difference is an addition. Existing rows keep their Options, and the
    highlight and scroll position stay on the same row.

    Returns ``False`` (caller falls back to a full ``update_list`` rebuild,
    and ``widget._insert_decline_reason`` says why) before mutating anything
    when a conservative gate makes the in-place path unsafe:

    - the widget holds no rows to insert into, or the grouping mode is not one
      of :data:`GroupingMode.STANDARD`, :data:`GroupingMode.BY_STATUS`, or
      :data:`GroupingMode.BY_MACHINE`, or it differs from the mode the widget
      was built under;
    - an existing agent changed, moved, or left (that is not an insert);
    - an added agent is a clan container or member, a session container, or a
      workflow parent or step;
    - the new grouping tree adds or removes a banner or spacer, or changes a
      banner's identity or selectability (this covers a new ``BY_STATUS``
      bucket and any change to ``rendered_group_keys``);
    - an existing row would render differently (context, gutter, tribe
      colors, machine chip, wait state), or an added row is wider than the
      alignment columns, because those are computed across every emitted row
      in ``build_list``.

    Banner chips are re-rendered from the new tree, so unlike
    ``try_remove_rows`` they do not drift.
    """
    widget._insert_decline_reason = None
    old_agents: list[Agent] = widget._agents
    old_entries = widget._row_entries
    if (
        widget._panel_collapsed
        or not old_agents
        or not old_entries
        or len(old_entries) != widget.option_count
    ):
        return _decline_insert(widget, None)
    if widget._grouping_mode not in _INPLACE_GROUPING_MODES:
        return _decline_insert(widget, "unsupported_grouping")
    if grouping_mode is not widget._grouping_mode:
        return _decline_insert(widget, "stale_grouping_mode")

    # The old list must be an ordered subsequence of the new one; whatever
    # else the new list holds is an insert.
    old_to_new: dict[int, int] = {}
    inserted: list[int] = []
    old_pos = 0
    for new_pos, agent in enumerate(agents):
        if old_pos < len(old_agents) and old_agents[old_pos].identity == agent.identity:
            if old_agents[old_pos] is not agent and old_agents[old_pos] != agent:
                return _decline_insert(widget, "panel_membership_change")
            old_to_new[old_pos] = new_pos
            old_pos += 1
        else:
            inserted.append(new_pos)
    if old_pos != len(old_agents):
        return _decline_insert(widget, "panel_membership_change")
    if not inserted:
        return _decline_insert(widget, None)
    if len({agent.identity for agent in agents}) != len(agents):
        return _decline_insert(widget, "panel_membership_change")
    if not all(_is_plain_leaf_row(agents[j]) for j in inserted):
        return _decline_insert(widget, "workflow_tree_change")

    tree = build_agent_tree(
        agents, fold_registry=fold_registry, mode=grouping_mode, now=now
    )
    tree = suppress_lone_machine_banner(
        tree, grouping_mode=grouping_mode, app=widget_app_or_none(widget)
    )
    panel_uses_cs = grouping_mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    agent_tier_styles, banner_tier_styles = compute_tier_styles(
        tree, panel_uses_cs=panel_uses_cs, mode=grouping_mode
    )
    visible = visible_agent_indices(tree)
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
    if inputs.tribe_colors != widget._tribe_identity_colors:
        return _decline_insert(widget, "panel_membership_change")

    # Existing rows keep their Options, so each must already paint exactly
    # what a rebuild would emit for it. Their Options move to the option id
    # their new position would get, keeping ids unique after the shift.
    inserted_set = set(inserted)
    new_to_old = {new: old for old, new in old_to_new.items()}
    agent_options: dict[int, Option] = {}
    row_contexts: dict[int, dict[str, Any]] = {}
    row_tier_styles: dict[int, tuple[str, ...]] = {}
    for new_idx in sorted(visible - inserted_set):
        old_idx = new_to_old[new_idx]
        old_ctx = widget._row_render_ctx.get(old_idx)
        old_row = widget._row_by_agent_idx.get(old_idx)
        tier_styles = agent_tier_styles.get(new_idx, ())
        if (
            old_ctx is None
            or old_row is None
            or not _same_row_context(
                old_ctx, agent_row_context(inputs, agents[new_idx], new_idx)
            )
            or widget._row_tier_styles.get(old_idx, ()) != tier_styles
        ):
            return _decline_insert(widget, "panel_membership_change")
        agent_options[new_idx] = _with_option_id(
            widget.get_option_at_index(old_row),
            agent_option_id(new_idx, agents[new_idx]),
        )
        row_contexts[new_idx] = old_ctx
        row_tier_styles[new_idx] = tier_styles

    for new_idx in inserted:
        if new_idx not in visible:
            continue  # inside a collapsed group: counted by its banner only
        agent = agents[new_idx]
        ctx = agent_row_context(inputs, agent, new_idx)
        tier_styles = agent_tier_styles.get(new_idx, ())
        left, suffix, option_id = format_agent_row(
            widget._agent_render_cache, inputs, agent, new_idx, ctx, tier_styles
        )
        if left.cell_len > widget._max_left or suffix.cell_len > widget._max_suffix:
            return _decline_insert(widget, "width_growth")
        agent_options[new_idx] = assemble_padded_option(
            left, suffix, width=widget._target_width, option_id=option_id
        )
        row_contexts[new_idx] = ctx
        row_tier_styles[new_idx] = tier_styles

    rows = emit_tree_rows(
        tree,
        agents,
        agent_options=agent_options,
        cache=widget._agent_render_cache,
        target_width=widget._target_width,
        banner_tier_styles=banner_tier_styles,
        banner_jump_hints=banner_jump_hints,
        grouping_mode=grouping_mode,
        marked=inputs.marked,
        current_idx=current_idx,
        current_group_key=current_group_key,
    )

    # Line the new tree up against the rows on screen: dropping the inserted
    # rows must leave exactly the old row sequence. Banners and spacers are
    # matched by position and id; a banner whose chip changed is swapped for
    # its re-rendered Option (never mutated, banners are shared with the cache).
    kept_rows = [
        row
        for row, (local_idx, _attempt) in enumerate(rows.row_entries)
        if local_idx not in inserted_set
    ]
    if len(kept_rows) != len(old_entries):
        return _decline_insert(widget, "status_membership_change")
    final_options = list(rows.options)
    old_row_to_new_row: dict[int, int] = {}
    for old_row, new_row in enumerate(kept_rows):
        old_local = old_entries[old_row][0]
        new_local = rows.row_entries[new_row][0]
        if (old_local == BANNER_ROW) != (new_local == BANNER_ROW):
            return _decline_insert(widget, "status_membership_change")
        if new_local == BANNER_ROW:
            old_option = widget.get_option_at_index(old_row)
            new_option = final_options[new_row]
            if (
                old_option.id != new_option.id
                or old_option.disabled != new_option.disabled
            ):
                return _decline_insert(widget, "status_membership_change")
            if old_option.prompt == new_option.prompt:
                final_options[new_row] = old_option
        elif old_to_new.get(old_local) != new_local:
            return _decline_insert(widget, "panel_membership_change")
        old_row_to_new_row[old_row] = new_row

    highlighted_row = rows.highlighted_row
    if highlighted_row is None and widget.highlighted is not None:
        highlighted_row = old_row_to_new_row.get(widget.highlighted)

    widget._programmatic_update = True
    try:
        try:
            widget.install_options(final_options)
        except (AttributeError, IndexError, DuplicateID):
            return _decline_insert(widget, "panel_membership_change")
        widget._agents = agents
        widget._row_entries = rows.row_entries
        widget._banner_at_row = rows.banner_at_row
        widget._group_at_row = rows.group_at_row
        widget._banner_hint_at_row = rows.banner_hint_at_row
        widget._banner_mark_at_row = rows.banner_mark_at_row
        widget._banner_row_by_key = rows.banner_row_by_key
        widget._row_by_agent_attempt = rows.row_by_agent_attempt
        widget._row_by_agent_idx = rows.row_by_agent_idx
        widget._row_render_ctx = row_contexts
        widget._row_tier_styles = row_tier_styles
        widget._unread_agents = set(inputs.unread)
        widget._rendered_group_folds = group_fold_snapshot(fold_registry)
        widget._content_requested_width = requested_panel_width(rows)
        widget._refresh_requested_width()
    finally:
        widget._programmatic_update = False
    if highlighted_row is not None:
        widget._set_highlighted_programmatically(highlighted_row)
    widget._rail_rows_changed()
    return True


__all__ = [
    "try_insert_rows",
]
