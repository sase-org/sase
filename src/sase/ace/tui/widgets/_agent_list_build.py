"""List-building and row-resolution helpers for :class:`AgentList`.

The widget delegates its full-rebuild path (``build_list``), single-row
patch path (``patch_row``), and pure tree/row analyses (``compute_*``,
``resolve_row``) here so ``agent_list.py`` stays focused on widget shell
concerns (bindings, messages, event wiring).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from rich.text import Text
from textual.widgets.option_list import Option

from ..agent_completion import (
    AgentWaitStatusMaps,
    agent_wait_status_maps_for_app,
    collect_agent_wait_status_maps,
    has_unresolvable_wait_target,
    missing_wait_dependency_names,
    wait_dependencies_satisfied,
)
from ..models.agent import Agent, AgentType
from ..models._agent_tree import (
    agent_fold_key,
    agent_is_tree_child,
    agent_parent_fold_key,
)
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    NO_HOUR_LABEL,
    TreeEntry,
    build_agent_tree,
)
from ..models.group_fold import GroupFoldView
from ..models.tribe_display import named_tribe_identity_colors
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    assemble_padded_option,
    cached_format_agent_option,
    cached_format_banner_option,
)
from ._agent_list_styling import (
    _BANNER_ROW,
    _PATCH_BANNER_RULE_STYLE,
    _MIN_BANNER_WIDTH,
    _PROJECT_BANNER_RULE_STYLE,
)

BannerMarkState = Literal["none", "partial", "all"]

# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports this
# module), and pyright infers ``Self@AgentList`` as a distinct type from
# the imported alias when ``Self`` flows through subclass-bound calls.
# ``Any`` keeps the helper self-contained while the widget API stays
# strongly typed in ``agent_list.py``.


def compute_visible_parents(
    agents: list[Agent],
) -> tuple[set[str], set[str]]:
    """Return ``(parents_with_visible_children, fully_expanded_parents)``."""
    parents_with_visible_children: set[str] = set()
    fully_expanded_parents: set[str] = set()
    for agent in agents:
        parent_key = agent_parent_fold_key(agent)
        if parent_key is not None:
            parents_with_visible_children.add(parent_key)
            if agent.is_hidden_step:
                fully_expanded_parents.add(parent_key)
    return parents_with_visible_children, fully_expanded_parents


def compute_tier_styles(
    tree: list[TreeEntry],
    *,
    panel_uses_cs: bool,
    mode: GroupingMode = GroupingMode.STANDARD,
) -> tuple[dict[int, tuple[str, ...]], list[tuple[str, ...]]]:
    """Walk *tree* and compute per-row tier-guide gutter styles.

    Returns ``(agent_tier_styles, banner_tier_styles)``:

    * ``agent_tier_styles[i]`` — the gutter for ``agents[i]``'s row.
    * ``banner_tier_styles[seq]`` — the gutter for the ``seq``-th
      banner emitted, in tree order.

    The gutter for a row is the list of visible ancestor tier styles that
    contribute a ``│  `` segment.  L0 (project / bucket) banners always
    contribute.  Middle-tier banners contribute the cooler Patch
    rule style: STANDARD L1 Patch banners, real BY_DATE L1 subgroup
    banners, and name-root banners that own dotted-name prefix subgroups.
    Terminal branch banners and synthetic ``(no time)`` buckets do not
    add a descendant tier.  Order is outermost first.
    """
    agent_styles: dict[int, tuple[str, ...]] = {}
    banner_styles: list[tuple[str, ...]] = []

    def is_stack_ancestor(
        parent_key: tuple[str, ...], child_key: tuple[str, ...]
    ) -> bool:
        return (
            len(parent_key) < len(child_key)
            and child_key[: len(parent_key)] == parent_key
        )

    def descendant_style_for(group: GroupRow) -> str | None:
        if group.level == 0:
            return _PROJECT_BANNER_RULE_STYLE
        if group.level == 1 and panel_uses_cs and len(group.group_key) == 2:
            return _PATCH_BANNER_RULE_STYLE
        if (
            group.level == 1
            and mode is GroupingMode.BY_DATE
            and group.group_key[-1] != NO_HOUR_LABEL
        ):
            return _PATCH_BANNER_RULE_STYLE
        if group.has_child_groups:
            return _PATCH_BANNER_RULE_STYLE
        return None

    active: list[tuple[tuple[str, ...], str]] = []
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            g = entry.group
            while active and not is_stack_ancestor(active[-1][0], g.group_key):
                active.pop()
            banner_styles.append(tuple(style for _, style in active))
            descendant_style = descendant_style_for(g)
            if descendant_style is not None:
                active.append((g.group_key, descendant_style))
            continue
        if entry.agent_idx is not None:
            agent_styles[entry.agent_idx] = tuple(style for _, style in active)
    return agent_styles, banner_styles


def resolve_row(
    option_index: int,
    row_entries: list[tuple[int, int | None]],
    banner_at_row: dict[int, GroupRow],
) -> tuple[int, int | None, tuple[str, ...] | None]:
    """Translate a raw OptionList row index to selection state.

    Returns ``(agent_idx, attempt_number, group_key)``.  When a
    selectable (collapsed) banner row is hit the ``group_key`` is the
    banner's :attr:`GroupRow.group_key` and ``agent_idx`` points at
    the first agent in the group so the detail panel still has
    something to show.  When a banner is non-selectable (its group
    is expanded) the row resolves to the next agent row.
    """
    if 0 <= option_index < len(row_entries):
        entry = row_entries[option_index]
        banner = banner_at_row.get(option_index)
        if banner is not None:
            first = banner.agent_indices[0] if banner.agent_indices else 0
            return (first, None, banner.group_key)
        if entry[0] == _BANNER_ROW:
            for j in range(option_index + 1, len(row_entries)):
                nxt = row_entries[j]
                if nxt[0] != _BANNER_ROW:
                    return (nxt[0], nxt[1], None)
            for j in range(option_index - 1, -1, -1):
                prv = row_entries[j]
                if prv[0] != _BANNER_ROW:
                    return (prv[0], prv[1], None)
            return (0, None, None)
        return (entry[0], entry[1], None)
    return (option_index, None, None)


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


def build_list(
    widget: Any,
    agents: list[Agent],
    current_idx: int,
    *,
    fold_counts: dict[str, tuple[int, int]] | None = None,
    marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
    unread_agents: set[tuple[AgentType, str, str | None]] | None = None,
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
        is_unread = agent.identity in unread
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
        has_missing_wait_target = bool(
            missing_wait_dependency_names(agent, status_buckets)
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
            is_unread=is_unread,
            hint_char=hint,
            tribe_label=tribe_label,
            panel_tribe=panel_tribe,
            tribe_colors=tribe_colors,
            now=now,
            tier_styles=tier_styles,
            wait_deps_satisfied=wait_deps_done,
            has_missing_wait_target=has_missing_wait_target,
            has_unresolvable_wait_target=has_unresolvable_wait,
            unread_agent_ids=unread,
        )
        agent_parts[i] = (left, suffix, option_id)
        widget._row_render_ctx[i] = {
            "fold_annotation": annotation,
            "is_expanded": is_expanded,
            "is_marked": is_marked,
            "is_unread": is_unread,
            "hint_char": hint,
            "tribe_label": tribe_label,
            "panel_tribe": panel_tribe,
            "tribe_colors": tribe_colors,
            "is_selected": is_selected_agent,
            "wait_deps_satisfied": wait_deps_done,
            "has_missing_wait_target": has_missing_wait_target,
            "has_unresolvable_wait_target": has_unresolvable_wait,
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


def try_remove_rows(
    widget: Any,
    removed_identities: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Apply optimistic removes in place; return ``True`` on success.

    Returns ``False`` (caller falls back to a full ``update_list`` rebuild)
    when any conservative gate makes the in-place path unsafe:

    - grouping mode is not :data:`GroupingMode.STANDARD`;
    - a removed agent is a workflow/clan parent with visible folded children
      (orphan child rows would be left behind);
    - the panel's per-row trackers don't have an entry for an identity we
      were asked to remove.

    Banner chip counts are not refreshed on the fast path — they heal on
    the next full refresh.
    """
    if widget._grouping_mode is not GroupingMode.STANDARD:
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
    # behind. Defense-in-depth — the caller should also gate.
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
    is_unread = agent.identity in effective_unread
    sel = ctx["is_selected"] if is_selected is None else is_selected
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
        is_unread=is_unread,
        hint_char=ctx["hint_char"],
        tribe_label=ctx.get("tribe_label"),
        panel_tribe=ctx.get("panel_tribe"),
        tribe_colors=ctx.get("tribe_colors"),
        now=now,
        tier_styles=widget._row_tier_styles.get(agent_idx, ()),
        wait_deps_satisfied=ctx.get("wait_deps_satisfied"),
        has_missing_wait_target=ctx.get("has_missing_wait_target", False),
        has_unresolvable_wait_target=ctx.get("has_unresolvable_wait_target", False),
        unread_agent_ids=effective_unread,
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
