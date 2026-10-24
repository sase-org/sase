"""Single-row in-place patch helpers for AgentList.

Part of the ``_agent_list_build_patching`` split: :func:`patch_row` and
:func:`patch_runtime_suffix_row`. Only public names cross module
boundaries here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ..agent_completion import (
    WaitDependencyStatusCounts,
    clan_unknown_wait_dependency_count,
)
from ..models.agent import AgentType
from ..models.agent_nodes import is_agents_tab_agent_node
from ._agent_list_build_rows import agent_wait_status_maps_for_build
from ._agent_list_rendering import (
    agent_option_id,
    assemble_padded_option,
    cached_format_agent_option,
    peek_cached_agent_option,
)

# Gap (2) plus the ✏️ live-hint glyph. Machine chips can consume the
# ``_MIN_BANNER_WIDTH`` slack that used to absorb this badge-only growth.
_LIVE_HINT_PATCH_SLACK = 4


# ``widget`` is the :class:`AgentList` instance.  Importing the class
# would create a circular import (``agent_list`` already imports the
# build facade). ``Any`` keeps the helpers self-contained while the
# widget API stays strongly typed in ``agent_list.py``.


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

    When the complete render inputs are unchanged (a render-cache hit at
    the same painted width) the row keeps its Option without calling
    ``replace_option_prompt_at_index``; per-row bookkeeping for future
    deltas is still updated. Returns ``False`` (caller falls back to a
    full ``update_list`` rebuild) when the agent isn't in this panel, the
    alignment width grew past the cached target, or the per-row context
    wasn't captured by a previous full render.
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
    wave_gutter = ctx.get("clan_wave_gutter")
    if (
        wave_gutter is not None
        and wave_gutter.bracket is not None
        and agent.clan_wave_slot is not None
    ):
        wave_gutter = replace(wave_gutter, open=agent.clan_wave_slot.open)
        ctx["clan_wave_gutter"] = wave_gutter
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
    tier_styles = widget._row_tier_styles.get(agent_idx, ())
    render_kwargs: dict[str, Any] = {
        "is_selected": sel,
        "fold_annotation": ctx["fold_annotation"],
        "is_expanded": ctx["is_expanded"],
        "is_marked": is_marked,
        "fold_restore_marked": ctx.get("fold_restore_marked", False),
        "is_unread": is_unread,
        "hint_char": ctx["hint_char"],
        "tribe_label": ctx.get("tribe_label"),
        "panel_tribe": ctx.get("panel_tribe"),
        "tribe_colors": ctx.get("tribe_colors"),
        "now": now,
        "tier_styles": tier_styles,
        "wait_deps_satisfied": ctx.get("wait_deps_satisfied"),
        "wait_dependency_counts": counts,
        "has_unresolvable_wait_target": ctx.get("has_unresolvable_wait_target", False),
        "clan_unknown_wait_count": clan_unknown,
        "unread_agent_ids": effective_unread,
        "show_machine_chip": bool(ctx.get("show_machine_chip", False)),
        "tab_chip": ctx.get("tab_chip"),
        "clan_wave_gutter": wave_gutter,
    }
    # Skip unchanged rows: a cache hit means the visible row is
    # byte-identical to the cached triple, so re-rendering would only
    # rebuild Text/Strip trees and replace an identical prompt. The
    # padding is part of the skip condition via the painted width the
    # full rebuild recorded: a changed target width repaints.
    hit = peek_cached_agent_option(
        widget._agent_render_cache, agent, agent_idx, **render_kwargs
    )
    if hit is not None and ctx.get("render_width") == widget._target_width:
        ctx["is_marked"] = is_marked
        ctx["is_unread"] = is_unread
        ctx["is_selected"] = sel
        ctx["wait_dependency_counts"] = counts
        ctx["clan_unknown_wait_count"] = clan_unknown
        try:
            last_left = getattr(widget, "_row_last_left_by_identity", None)
            last_suffix = getattr(widget, "_row_last_suffix_plain_by_identity", None)
            if isinstance(last_left, dict):
                last_left[agent.identity] = hit[0]
            if isinstance(last_suffix, dict):
                last_suffix[agent.identity] = hit[1].plain
        except Exception:  # noqa: BLE001 - runtime fast-path bookkeeping only.
            pass
        return True
    # Bust the cached entry for this agent so the re-render below cannot
    # return a stale entry and stale keys for this identity do not pile
    # up behind the fresh one.
    widget._agent_render_cache.invalidate_agent(agent.identity)

    left, suffix, option_id = cached_format_agent_option(
        widget._agent_render_cache,
        agent,
        agent_idx,
        **render_kwargs,
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
    ctx["render_width"] = widget._target_width
    try:
        last_left = getattr(widget, "_row_last_left_by_identity", None)
        last_suffix = getattr(widget, "_row_last_suffix_plain_by_identity", None)
        if isinstance(last_left, dict):
            last_left[agent.identity] = left
        if isinstance(last_suffix, dict):
            last_suffix[agent.identity] = suffix.plain
    except Exception:  # noqa: BLE001 - runtime fast-path bookkeeping only.
        pass

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


def patch_runtime_suffix_row(widget: Any, agent_idx: int, now: datetime) -> bool:
    """Patch one ticking row's runtime suffix alone; return True when painted.

    Change-only (phase ``runtime-tick-caches``): recomputes only the
    right-side runtime suffix via :func:`build_runtime_suffix` and skips the
    row when its plain text is unchanged. A changed suffix reuses the stored
    left Text and assembles a new Option without invalidating the full row
    render cache entry. Falls back to :func:`patch_row` when no baseline
    exists, the width would grow past the cached target, or the stored left
    is missing; a fallback failure returns False so the next full refresh
    rebuilds the row.
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
    try:
        from ..models.agent_nodes import is_agents_tab_agent_node as _is_node
    except Exception:  # noqa: BLE001 - display-only fallback.
        _is_node = is_agents_tab_agent_node
    try:
        from ._agent_list_render_layout import build_runtime_suffix
    except Exception:  # noqa: BLE001 - fallback covers render import issues.
        return patch_row(widget, agent_idx, now=now)
    try:
        effective_unread: set[Any] = getattr(widget, "_unread_agents", set())
        is_unread = agent.identity in effective_unread and _is_node(agent)
        new_suffix = build_runtime_suffix(agent, now=now, is_unread=is_unread)
    except Exception:  # noqa: BLE001 - suffix compute must not break the tick.
        return False
    try:
        last_suffix = getattr(widget, "_row_last_suffix_plain_by_identity", {})
        old_plain = last_suffix.get(agent.identity)
    except Exception:  # noqa: BLE001 - defensive cache read only.
        old_plain = None
    if old_plain is None:
        return patch_row(widget, agent_idx, now=now)
    try:
        new_plain = new_suffix.plain
    except Exception:  # noqa: BLE001 - defensive text read only.
        return patch_row(widget, agent_idx, now=now)
    if new_plain == old_plain:
        return False
    try:
        last_left = getattr(widget, "_row_last_left_by_identity", {})
        left = last_left.get(agent.identity)
    except Exception:  # noqa: BLE001 - defensive cache read only.
        left = None
    if left is None:
        return patch_row(widget, agent_idx, now=now)
    gap = 2 if new_suffix.cell_len else 0
    try:
        target_width = int(widget._target_width)
    except Exception:  # noqa: BLE001 - defensive width read only.
        return patch_row(widget, agent_idx, now=now)
    if (
        left.cell_len + gap + new_suffix.cell_len
        > target_width + _LIVE_HINT_PATCH_SLACK
    ):
        return patch_row(widget, agent_idx, now=now)
    try:
        option_id = agent_option_id(agent_idx, agent)
        new_option = assemble_padded_option(
            left, new_suffix, width=target_width, option_id=option_id
        )
    except Exception:  # noqa: BLE001 - assembly must not break the tick.
        return patch_row(widget, agent_idx, now=now)
    widget._programmatic_update = True
    try:
        widget.replace_option_prompt_at_index(row, new_option.prompt)
    except (AttributeError, IndexError):
        return False
    finally:
        widget._programmatic_update = False
    try:
        last_suffix[agent.identity] = new_plain
    except Exception:  # noqa: BLE001 - bookkeeping only.
        pass
    return True


__all__ = [
    "patch_row",
    "patch_runtime_suffix_row",
]
