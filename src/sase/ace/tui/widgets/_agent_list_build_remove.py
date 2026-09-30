"""In-place row removal for AgentList.

Part of the ``_agent_list_build_patching`` split: :func:`try_remove_rows`.
Only public names cross module boundaries here.
"""

from __future__ import annotations

from typing import Any

from ..models.agent import AgentType
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    rendered_group_keys,
)
from ._agent_list_styling import BANNER_ROW


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
            if (
                other.is_agent_session_member_child
                or other.parent_workflow == agent.workflow
            ):
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
    new_group_at_row: dict[int, GroupRow] = {}
    new_banner_hint_at_row: dict[int, str | None] = {}
    new_banner_mark_at_row: dict[int, str] = {}
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
        if local_idx == BANNER_ROW:
            new_row_entries.append(entry)
            banner = widget._banner_at_row.get(old_row_idx)
            if banner is not None:
                new_banner_at_row[new_row_idx] = banner
                new_banner_row_by_key[banner.group_key] = new_row_idx
            group = widget._group_at_row.get(old_row_idx)
            if group is not None:
                new_group_at_row[new_row_idx] = group
                new_banner_hint_at_row[new_row_idx] = widget._banner_hint_at_row.get(
                    old_row_idx
                )
                new_banner_mark_at_row[new_row_idx] = widget._banner_mark_at_row.get(
                    old_row_idx, "none"
                )
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
    widget._group_at_row = new_group_at_row
    widget._banner_hint_at_row = new_banner_hint_at_row
    widget._banner_mark_at_row = new_banner_mark_at_row
    widget._row_by_agent_attempt = new_row_by_agent_attempt
    widget._row_by_agent_idx = new_row_by_agent_idx
    widget._banner_row_by_key = new_banner_row_by_key
    widget._row_render_ctx = new_row_render_ctx
    widget._row_tier_styles = new_row_tier_styles
    try:
        last_left = getattr(widget, "_row_last_left_by_identity", None)
        last_suffix = getattr(widget, "_row_last_suffix_plain_by_identity", None)
        if isinstance(last_left, dict):
            for identity in removed_identities:
                last_left.pop(identity, None)
        if isinstance(last_suffix, dict):
            for identity in removed_identities:
                last_suffix.pop(identity, None)
    except Exception:  # noqa: BLE001 - bookkeeping only.
        pass

    widget._rail_rows_changed()

    return True


__all__ = [
    "try_remove_rows",
]
