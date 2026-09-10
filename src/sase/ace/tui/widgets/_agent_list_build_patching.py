"""Incremental AgentList row mutation helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..agent_completion import WaitDependencyStatusCounts
from ..models.agent import AgentType
from ..models.agent_groups import GroupRow, GroupingMode
from ..models.agent_nodes import is_agents_tab_agent_node
from ._agent_list_rendering import assemble_padded_option, cached_format_agent_option
from ._agent_list_styling import _BANNER_ROW


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

    - grouping mode is neither :data:`GroupingMode.STANDARD` nor
      :data:`GroupingMode.BY_MACHINE`;
    - a removed agent is a workflow/clan parent with visible folded children
      (orphan child rows would be left behind);
    - the panel's per-row trackers don't have an entry for an identity we
      were asked to remove.

    Banner chip counts are not refreshed on the fast path - they heal on
    the next full refresh.
    """
    if widget._grouping_mode not in {GroupingMode.STANDARD, GroupingMode.BY_MACHINE}:
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
        unread_agent_ids=effective_unread,
        show_machine_chip=bool(ctx.get("show_machine_chip", False)),
        show_fleet_badge=bool(ctx.get("show_fleet_badge", False)),
    )

    gap = 2 if suffix.cell_len else 0
    if left.cell_len + gap + suffix.cell_len > widget._target_width:
        return False

    new_option = assemble_padded_option(
        left, suffix, width=widget._target_width, option_id=option_id
    )

    ctx["is_marked"] = is_marked
    ctx["is_unread"] = is_unread
    ctx["is_selected"] = sel
    ctx["wait_dependency_counts"] = counts

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


__all__ = [
    "patch_row",
    "try_remove_rows",
]
