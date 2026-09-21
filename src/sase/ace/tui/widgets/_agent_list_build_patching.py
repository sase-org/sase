"""Incremental AgentList row mutation helpers."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from textual.widgets.option_list import DuplicateID, Option

from ..agent_completion import (
    WaitDependencyStatusCounts,
    clan_unknown_wait_dependency_count,
)
from ..models.agent import Agent, AgentType
from ..models.agent_groups import (
    GroupRow,
    GroupingMode,
    build_agent_tree,
    rendered_group_keys,
)
from ..models.agent_nodes import is_agents_tab_agent_node
from ..models.group_fold import GroupFoldView
from ._agent_list_build_analysis import compute_tier_styles, visible_agent_indices
from ._agent_list_build_rows import (
    agent_row_context,
    agent_wait_status_maps_for_build,
    build_row_inputs,
    emit_tree_rows,
    format_agent_row,
    requested_panel_width,
)
from ._agent_list_rendering import (
    agent_option_id,
    assemble_padded_option,
    cached_format_agent_option,
)
from ._agent_list_styling import _BANNER_ROW

# Gap (2) plus the ✏️ live-hint glyph. Machine chips can consume the
# ``_MIN_BANNER_WIDTH`` slack that used to absorb this badge-only growth.
_LIVE_HINT_PATCH_SLACK = 4


# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports the
# build facade). ``Any`` keeps the helpers self-contained while the
# widget API stays strongly typed in ``agent_list.py``.


def try_remove_rows(
    widget: Any,
    removed_identities: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Apply optimistic removes in place; return ``True`` on success.

    Returns ``False`` (caller falls back to a full ``update_list`` rebuild)
    when any conservative gate makes the in-place path unsafe:

    - grouping mode is not one of :data:`GroupingMode.STANDARD`,
      :data:`GroupingMode.BY_STATUS`, or :data:`GroupingMode.BY_MACHINE`;
    - a ``BY_STATUS`` removal would add/remove a status bucket or group banner;
    - a removed agent is a workflow/clan parent with visible folded children
      (orphan child rows would be left behind);
    - the panel's per-row trackers don't have an entry for an identity we
      were asked to remove.

    Banner chip counts are not refreshed on the fast path - they heal on
    the next full refresh.
    """
    if widget._grouping_mode not in {
        GroupingMode.STANDARD,
        GroupingMode.BY_STATUS,
        GroupingMode.BY_MACHINE,
    }:
        return False

    rows_to_remove: list[tuple[int, int]] = []
    removed_local_set: set[int] = set()
    for local_idx, agent in enumerate(widget._agents):
        if agent.identity not in removed_identities:
            continue
        # Clan rows and members affect a synthetic container's count, status,
        # runtime, and descendant topology. Let the caller rebuild that small
        # in-memory projection instead of stranding a stale container row.
        if agent.is_clan_container or agent.tree_parent_key:
            return False
        row = widget._row_by_agent_idx.get(local_idx)
        if row is None:
            return False
        rows_to_remove.append((row, local_idx))
        removed_local_set.add(local_idx)

    if not rows_to_remove:
        return True

    if widget._grouping_mode is GroupingMode.BY_STATUS:
        remaining_agents = [
            agent
            for agent in widget._agents
            if agent.identity not in removed_identities
        ]
        if rendered_group_keys(
            widget._agents,
            GroupingMode.BY_STATUS,
        ) != rendered_group_keys(remaining_agents, GroupingMode.BY_STATUS):
            return False

    # Parent gate: a parent with visible children would leave orphan rows
    # behind. Defense-in-depth: the caller should also gate.
    for _, local_idx in rows_to_remove:
        agent = widget._agents[local_idx]
        if agent.is_child_row or not agent.raw_suffix:
            continue
        for other in widget._agents:
            if not (other.is_child_row and other.parent_timestamp == agent.raw_suffix):
                continue
            if other.is_family_member_child or other.parent_workflow == agent.workflow:
                return False

    rows_to_remove.sort(key=lambda t: t[0], reverse=True)
    removed_row_set = {row for row, _ in rows_to_remove}

    widget._programmatic_update = True
    try:
        for row, _ in rows_to_remove:
            try:
                widget.remove_option_at_index(row)
            except (AttributeError, IndexError):
                widget._programmatic_update = False
                return False
    finally:
        widget._programmatic_update = False

    # Remap local agent indices: dropping a removed agent shifts every
    # later agent down by 1.
    old_to_new_local: dict[int, int] = {}
    new_local = 0
    for old_local in range(len(widget._agents)):
        if old_local in removed_local_set:
            continue
        old_to_new_local[old_local] = new_local
        new_local += 1

    new_agents = [
        a for li, a in enumerate(widget._agents) if li not in removed_local_set
    ]

    new_row_entries: list[tuple[int, int | None]] = []
    new_banner_at_row: dict[int, GroupRow] = {}
    new_row_by_agent_attempt: dict[tuple[int, int | None], int] = {}
    new_row_by_agent_idx: dict[int, int] = {}
    new_banner_row_by_key: dict[tuple[str, ...], int] = {}
    new_row_render_ctx: dict[int, dict[str, Any]] = {}
    new_row_tier_styles: dict[int, tuple[str, ...]] = {}

    new_row_idx = 0
    for old_row_idx, entry in enumerate(widget._row_entries):
        if old_row_idx in removed_row_set:
            continue
        local_idx, attempt = entry
        if local_idx == _BANNER_ROW:
            new_row_entries.append(entry)
            banner = widget._banner_at_row.get(old_row_idx)
            if banner is not None:
                new_banner_at_row[new_row_idx] = banner
                new_banner_row_by_key[banner.group_key] = new_row_idx
        else:
            new_li = old_to_new_local[local_idx]
            new_row_entries.append((new_li, attempt))
            new_row_by_agent_attempt[(new_li, attempt)] = new_row_idx
            if attempt is None:
                new_row_by_agent_idx[new_li] = new_row_idx
            ctx = widget._row_render_ctx.get(local_idx)
            if ctx is not None:
                new_row_render_ctx[new_li] = ctx
            tier = widget._row_tier_styles.get(local_idx)
            if tier is not None:
                new_row_tier_styles[new_li] = tier
        new_row_idx += 1

    widget._agents = new_agents
    widget._row_entries = new_row_entries
    widget._banner_at_row = new_banner_at_row
    widget._row_by_agent_attempt = new_row_by_agent_attempt
    widget._row_by_agent_idx = new_row_by_agent_idx
    widget._banner_row_by_key = new_banner_row_by_key
    widget._row_render_ctx = new_row_render_ctx
    widget._row_tier_styles = new_row_tier_styles

    return True


def patch_row(
    widget: Any,
    agent_idx: int,
    *,
    marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
    unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
    is_selected: bool | None = None,
    now: datetime | None = None,
    wait_dependency_counts: WaitDependencyStatusCounts | None = None,
) -> bool:
    """Replace one agent row's Option in place; return ``True`` on success.

    Returns ``False`` (caller falls back to a full ``update_list`` rebuild)
    when the agent isn't in this panel, the alignment width grew past the
    cached target, or the per-row context wasn't captured by a previous
    full render.
    """
    if not (0 <= agent_idx < len(widget._agents)):
        return False
    ctx = widget._row_render_ctx.get(agent_idx)
    if ctx is None:
        return False
    row = widget._row_by_agent_idx.get(agent_idx)
    if row is None:
        return False

    agent = widget._agents[agent_idx]
    is_marked = (
        ctx["is_marked"] if marked_agents is None else agent.identity in marked_agents
    )
    effective_unread = (
        getattr(widget, "_unread_agents", set())
        if unread_agents is None
        else unread_agents
    )
    if unread_agents is not None:
        widget._unread_agents = set(unread_agents)
    is_unread = agent.identity in effective_unread and is_agents_tab_agent_node(agent)
    sel = ctx["is_selected"] if is_selected is None else is_selected
    counts = (
        ctx.get("wait_dependency_counts")
        if wait_dependency_counts is None
        else wait_dependency_counts
    )
    if agent.is_clan_container:
        wait_status_maps = agent_wait_status_maps_for_build(widget, widget._agents)
        clan_unknown = clan_unknown_wait_dependency_count(agent, wait_status_maps)
    else:
        clan_unknown = 0
    # Bust the cached entry for this agent so we re-render from
    # current field values; the patch path is the only writer of
    # mid-list mutations and must not return a stale cache hit.
    widget._agent_render_cache.invalidate_agent(agent.identity)

    left, suffix, option_id = cached_format_agent_option(
        widget._agent_render_cache,
        agent,
        agent_idx,
        is_selected=sel,
        fold_annotation=ctx["fold_annotation"],
        is_expanded=ctx["is_expanded"],
        is_marked=is_marked,
        fold_restore_marked=ctx.get("fold_restore_marked", False),
        is_unread=is_unread,
        hint_char=ctx["hint_char"],
        tribe_label=ctx.get("tribe_label"),
        panel_tribe=ctx.get("panel_tribe"),
        tribe_colors=ctx.get("tribe_colors"),
        now=now,
        tier_styles=widget._row_tier_styles.get(agent_idx, ()),
        wait_deps_satisfied=ctx.get("wait_deps_satisfied"),
        wait_dependency_counts=counts,
        has_unresolvable_wait_target=ctx.get("has_unresolvable_wait_target", False),
        clan_unknown_wait_count=clan_unknown,
        unread_agent_ids=effective_unread,
        show_machine_chip=bool(ctx.get("show_machine_chip", False)),
    )

    gap = 2 if suffix.cell_len else 0
    if (
        left.cell_len + gap + suffix.cell_len
        > widget._target_width + _LIVE_HINT_PATCH_SLACK
    ):
        return False

    new_option = assemble_padded_option(
        left, suffix, width=widget._target_width, option_id=option_id
    )

    ctx["is_marked"] = is_marked
    ctx["is_unread"] = is_unread
    ctx["is_selected"] = sel
    ctx["wait_dependency_counts"] = counts
    ctx["clan_unknown_wait_count"] = clan_unknown

    widget._programmatic_update = True
    try:
        # Textual's OptionList exposes ``replace_option_prompt_at_index``;
        # the option_id (and therefore ``_id_to_option`` mapping) is
        # preserved by ``format_agent_option`` since it derives from
        # ``(index, agent_type, cl_name)`` which don't change for a
        # single-row mutation.
        widget.replace_option_prompt_at_index(row, new_option.prompt)
    except (AttributeError, IndexError):
        return False
    finally:
        widget._programmatic_update = False
    return True


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

    Clan containers and members, family containers, and workflow parents and
    steps change a synthetic container row or a descendant topology that only
    a rebuild reprojects, so they are never inserted in place.
    """
    return not (
        agent.is_clan_container
        or agent.agent_clan
        or agent.is_family_container_row
        or agent.is_imported_family_container
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

    The mirror of :func:`try_remove_rows`. *agents* is the panel's full new
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
    - an added agent is a clan container or member, a family container, or a
      workflow parent or step;
    - the new grouping tree adds or removes a banner or spacer, or changes a
      banner's identity or selectability (this covers a new ``BY_STATUS``
      bucket and any change to ``rendered_group_keys``);
    - an existing row would render differently (context, gutter, tribe
      colors, machine chip, wait state), or an added row is wider than the
      alignment columns, because those are computed across every emitted row
      in ``build_list``.

    Banner chips are re-rendered from the new tree, so unlike
    :func:`try_remove_rows` they do not drift.
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
        if (old_local == _BANNER_ROW) != (new_local == _BANNER_ROW):
            return _decline_insert(widget, "status_membership_change")
        if new_local == _BANNER_ROW:
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
        widget._banner_row_by_key = rows.banner_row_by_key
        widget._row_by_agent_attempt = rows.row_by_agent_attempt
        widget._row_by_agent_idx = rows.row_by_agent_idx
        widget._row_render_ctx = row_contexts
        widget._row_tier_styles = row_tier_styles
        widget._unread_agents = set(inputs.unread)
        widget._content_requested_width = requested_panel_width(rows)
        widget._refresh_requested_width()
    finally:
        widget._programmatic_update = False
    if highlighted_row is not None:
        widget._set_highlighted_programmatically(highlighted_row)
    return True


__all__ = [
    "patch_row",
    "try_insert_rows",
    "try_remove_rows",
]
