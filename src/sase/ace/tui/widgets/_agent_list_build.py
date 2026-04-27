"""List-building and row-resolution helpers for :class:`AgentList`.

The widget delegates its full-rebuild path (``build_list``), single-row
patch path (``patch_row``), and pure tree/row analyses (``compute_*``,
``resolve_row``) here so ``agent_list.py`` stays focused on widget shell
concerns (bindings, messages, event wiring).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from ..models.agent_group_fold import AgentGroupFoldRegistry
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    TreeEntry,
    build_agent_tree,
)
from ._agent_list_helpers import compute_fold_annotation
from ._agent_list_rendering import (
    assemble_padded_option,
    cached_format_agent_option,
    cached_format_banner_option,
)
from ._agent_list_styling import (
    _BANNER_ROW,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _MIN_BANNER_WIDTH,
    _PROJECT_BANNER_RULE_STYLE,
)

# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports this
# module), and pyright infers ``Self@AgentList`` as a distinct type from
# the imported alias when ``Self`` flows through subclass-bound calls.
# ``Any`` keeps the helper self-contained while the widget API stays
# strongly typed in ``agent_list.py``.


def _compute_visible_parents(
    agents: list[Agent],
) -> tuple[set[str], set[str]]:
    """Return ``(parents_with_visible_children, fully_expanded_parents)``."""
    parents_with_visible_children: set[str] = set()
    fully_expanded_parents: set[str] = set()
    for agent in agents:
        if agent.is_workflow_child and agent.parent_timestamp:
            parents_with_visible_children.add(agent.parent_timestamp)
            if agent.is_hidden_step:
                fully_expanded_parents.add(agent.parent_timestamp)
    return parents_with_visible_children, fully_expanded_parents


def compute_tier_styles(
    tree: list[TreeEntry],
    *,
    panel_uses_cs: bool,
) -> tuple[dict[int, tuple[str, ...]], list[tuple[str, ...]]]:
    """Walk *tree* and compute per-row tier-guide gutter styles.

    Returns ``(agent_tier_styles, banner_tier_styles)``:

    * ``agent_tier_styles[i]`` — the gutter for ``agents[i]``'s row.
    * ``banner_tier_styles[seq]`` — the gutter for the ``seq``-th
      banner emitted, in tree order.

    The gutter for a row is the list of ancestor tier styles that
    contribute a ``│  `` segment.  L0 (project / bucket) and L1
    ChangeSpec banners contribute; L1/L2 name-root banners do not
    (the indent already groups their agents).  Order is outermost
    first.
    """
    agent_styles: dict[int, tuple[str, ...]] = {}
    banner_styles: list[tuple[str, ...]] = []
    cur_l0: str | None = None
    cur_l1: str | None = None
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            g = entry.group
            if g.level == 0:
                banner_styles.append(())
                cur_l0 = _PROJECT_BANNER_RULE_STYLE
                cur_l1 = None
            elif g.level == 1 and panel_uses_cs and len(g.group_key) == 2:
                banner_styles.append((cur_l0,) if cur_l0 is not None else ())
                cur_l1 = _CHANGESPEC_BANNER_RULE_STYLE
            else:
                banner_styles.append(
                    tuple(s for s in (cur_l0, cur_l1) if s is not None)
                )
            continue
        if entry.agent_idx is not None:
            agent_styles[entry.agent_idx] = tuple(
                s for s in (cur_l0, cur_l1) if s is not None
            )
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


def build_list(
    widget: Any,
    agents: list[Agent],
    current_idx: int,
    *,
    fold_counts: dict[str, tuple[int, int]] | None = None,
    marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
    jump_hints: dict[int, str] | None = None,
    banner_jump_hints: dict[tuple[str, ...], str] | None = None,
    fold_registry: AgentGroupFoldRegistry | None = None,
    current_group_key: tuple[str, ...] | None = None,
    grouping_mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> None:
    """Rebuild *widget*'s OptionList from scratch for ``agents``.

    Mutates the widget's per-row state maps (``_row_entries``,
    ``_row_render_ctx``, etc.) and posts a :class:`WidthChanged`
    message so the container can resize.
    """
    widget._programmatic_update = True
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

    parents_with_visible_children, fully_expanded_parents = _compute_visible_parents(
        agents
    )

    widget._grouping_mode = grouping_mode
    tree: list[TreeEntry] = build_agent_tree(
        agents, fold_registry=fold_registry, mode=grouping_mode, now=now
    )
    panel_uses_cs = grouping_mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    agent_tier_styles, banner_tier_styles = compute_tier_styles(
        tree, panel_uses_cs=panel_uses_cs
    )

    # Pre-format agent rows so we know their widths before emitting banner
    # rules (banners are stretched to the widest row, and the runtime
    # suffix is right-aligned to the same column).
    agent_parts: dict[int, tuple[Any, Any, str]] = {}
    max_left = 0
    max_suffix = 0
    for i, agent in enumerate(agents):
        is_expanded = (
            agent.raw_suffix is not None
            and agent.raw_suffix in parents_with_visible_children
        )
        is_marked = agent.identity in marked
        annotation = compute_fold_annotation(
            agent,
            fold_counts,
            parents_with_visible_children,
            fully_expanded_parents,
        )
        is_selected_agent = current_group_key is None and i == current_idx
        hint = (jump_hints or {}).get(i)
        tier_styles = agent_tier_styles.get(i, ())
        left, suffix, option_id = cached_format_agent_option(
            widget._agent_render_cache,
            agent,
            i,
            is_selected=is_selected_agent,
            fold_annotation=annotation,
            is_expanded=is_expanded,
            is_marked=is_marked,
            hint_char=hint,
            now=now,
            tier_styles=tier_styles,
        )
        agent_parts[i] = (left, suffix, option_id)
        widget._row_render_ctx[i] = {
            "fold_annotation": annotation,
            "is_expanded": is_expanded,
            "is_marked": is_marked,
            "hint_char": hint,
            "is_selected": is_selected_agent,
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

    # Walk the grouping tree and emit Options in display order.
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
                    widget.add_option(spacer)
                    widget._row_entries.append((_BANNER_ROW, None))
                seen_first_l0 = True
            banner_selectable = entry.group.is_collapsed
            tier_styles_for_banner = (
                banner_tier_styles[banner_seq]
                if banner_seq < len(banner_tier_styles)
                else ()
            )
            banner_hint = (
                (banner_jump_hints or {}).get(entry.group.group_key)
                if banner_selectable
                else None
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
            )
            banner_seq += 1
            row_index = len(widget._row_entries)
            widget.add_option(option)
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
        widget.add_option(option)
        is_selected_agent = current_group_key is None and i == current_idx
        row_index = len(widget._row_entries)
        if is_selected_agent:
            highlighted_row = row_index
        widget._row_entries.append((i, None))
        widget._row_by_agent_attempt[(i, None)] = row_index
        widget._row_by_agent_idx[i] = row_index

    # Add padding for border, scrollbar, visual comfort (~8 cells)
    _PADDING = 8
    optimal_width = max(max_width, banner_width) + _PADDING
    widget.post_message(widget.WidthChanged(optimal_width))

    try:
        if highlighted_row is not None:
            widget.highlighted = highlighted_row
    finally:
        widget._programmatic_update = False


def patch_row(
    widget: Any,
    agent_idx: int,
    *,
    marked_agents: set[tuple[AgentType, str, str | None]] | None = None,
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
    marked = marked_agents if marked_agents is not None else set()
    is_marked = agent.identity in marked
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
        hint_char=ctx["hint_char"],
        now=now,
        tier_styles=widget._row_tier_styles.get(agent_idx, ()),
    )

    gap = 2 if suffix.cell_len else 0
    if left.cell_len + gap + suffix.cell_len > widget._target_width:
        return False

    new_option = assemble_padded_option(
        left, suffix, width=widget._target_width, option_id=option_id
    )

    ctx["is_marked"] = is_marked
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
