"""One batched chrome helper for unread changes.

Phase ``unread-chrome-helper`` (epic ``sase-1d7``): every unread change
(bulk mark, single ack, undo restore, failure rollback, every reconcile
path) paints through :func:`apply_unread_chrome`, which patches only
visible changed rows via an identity map, skips collapsed panels and
off-tab rows, never falls back to a full rebuild, and refreshes titles,
the info panel, the machine chip / tab strip header, and the tribe
summary once each on the same paint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey


def _member_clan_key(agent: Agent) -> tuple[str, str | None] | None:
    """Return the ``(clan, generation)`` key for a clan member, if any."""
    if not agent.agent_clan:
        return None
    return (agent.agent_clan, agent.agent_clan_generation)


def _call_row_patch(try_patch: Any, agent: Agent) -> bool:
    """Patch one row without per-row chrome; tolerate narrow test doubles.

    The real ``_try_patch_agent_row`` accepts ``refresh_info`` and
    ``refresh_title`` keywords. Older test doubles only take the agent, so
    fall back through narrower signatures before reporting failure.
    """
    try:
        return bool(try_patch(agent, refresh_info=False, refresh_title=False))
    except TypeError:
        pass
    try:
        return bool(try_patch(agent, refresh_info=False))
    except TypeError:
        pass
    return bool(try_patch(agent))


def apply_unread_chrome(
    app: Any,
    before: set[tuple[AgentType, str, str | None]],
    *,
    status_changed: set[tuple[AgentType, str, str | None]]
    | tuple[tuple[AgentType, str, str | None], ...] = (),
) -> bool:
    """Paint an unread diff; always ``True`` (never needs a full rebuild)."""
    from sase.ace.tui.util.trace import tui_trace

    with tui_trace("unread.chrome_apply") as extra:
        ok, counters = _apply_unread_chrome(app, before, status_changed=status_changed)
        extra.update(counters)
        return ok


def _apply_unread_chrome(
    app: Any,
    before: set[tuple[AgentType, str, str | None]],
    *,
    status_changed: set[tuple[AgentType, str, str | None]]
    | tuple[tuple[AgentType, str, str | None], ...] = (),
) -> tuple[bool, dict[str, int]]:
    """Implement :func:`apply_unread_chrome` and return span counters."""
    after: set[tuple[AgentType, str, str | None]] = set(
        getattr(app, "_unread_completed_agent_ids", set()) or set()
    )
    before_set = set(before or ())
    changed = before_set ^ after
    status_changed_set = set(status_changed or ())
    if not changed and not status_changed_set:
        return True, {
            "changed": 0,
            "visible_patched": 0,
            "collapsed_skipped": 0,
            "panel_rebuilds": 0,
            "patch_failed": 0,
        }
    if getattr(app, "current_tab", None) != "agents":
        # Off-tab rows: only counts change, painted when the tab returns.
        return True, {
            "changed": len(changed),
            "visible_patched": 0,
            "collapsed_skipped": 0,
            "panel_rebuilds": 0,
            "patch_failed": 0,
        }

    combined = set(changed) | status_changed_set

    from ._notification_agent_targeting import loaded_real_agent_roster

    roster = loaded_real_agent_roster(app)
    node_index = None
    try:
        from ._roster_generation import cached_agent_node_projection_index

        node_index = cached_agent_node_projection_index(app, roster)
    except Exception:
        node_index = None
    changed_node_identities: set[tuple[AgentType, str, str | None]] = set()
    if node_index is not None:
        for identity in combined:
            try:
                projection = node_index.owner_for_identity(identity)
            except Exception:
                projection = None
            if projection is not None:
                changed_node_identities.add(projection.identity)
    roster_agents = {agent.identity: agent for agent in roster}
    affected_clans = {
        clan_key
        for identity in combined
        if (member := roster_agents.get(identity)) is not None
        and (clan_key := _member_clan_key(member)) is not None
    }

    agents_list: list[Agent] = list(getattr(app, "_agents", ()) or ())
    # Identity map: O(1) row resolution without ``list.index`` scans, and a
    # live read of ``_agents`` so no extra invalidation is needed beyond the
    # panel-index cache the panel keys below already ride on.
    index_by_identity: dict[tuple[AgentType, str, str | None], int] = {}
    for idx, agent in enumerate(agents_list):
        index_by_identity.setdefault(agent.identity, idx)

    panel_index = None
    panel_index_fn = getattr(app, "_agent_panel_index", None)
    if callable(panel_index_fn):
        try:
            panel_index = panel_index_fn()
        except Exception:
            panel_index = None
    keys_per_agent: list[PanelKey] | None = None
    if panel_index is not None:
        try:
            keys_per_agent = list(panel_index.keys_per_agent)
        except Exception:
            keys_per_agent = None
    if keys_per_agent is None:
        legacy_keys_fn = getattr(app, "_panel_keys_per_agent", None)
        if callable(legacy_keys_fn):
            try:
                keys_per_agent = list(legacy_keys_fn())
            except Exception:
                keys_per_agent = None

    collapsed_keys: set[PanelKey] = set()
    panel_group = getattr(app, "_panel_group", None)
    if panel_group is not None:
        try:
            from ._panel_fold_intent import effective_panel_collapses

            collapsed_keys = set(effective_panel_collapses(app, panel_group.panel_keys))
        except Exception:
            collapsed_keys = set()

    # Display-order candidates: terminal members plus visible clan ancestors.
    patch_plan: list[tuple[Agent, PanelKey | None, int]] = []
    patch_keys: set[object] = set()
    for identity, global_idx in index_by_identity.items():
        agent = agents_list[global_idx]
        if agent.is_clan_container:
            clan_key = (
                (agent.agent_clan, agent.agent_clan_generation)
                if agent.agent_clan
                else None
            )
            if clan_key is None or clan_key not in affected_clans:
                continue
            patch_key: object = ("clan", *clan_key)
        else:
            if identity not in combined and identity not in changed_node_identities:
                continue
            patch_key = ("agent", identity)
        if patch_key in patch_keys:
            continue
        patch_keys.add(patch_key)
        panel_key: PanelKey | None = None
        if keys_per_agent is not None and 0 <= global_idx < len(keys_per_agent):
            try:
                panel_key = keys_per_agent[global_idx]
            except Exception:
                panel_key = None
        patch_plan.append((agent, panel_key, global_idx))

    try_patch = getattr(app, "_try_patch_agent_row", None)
    query_one = getattr(app, "query_one", None)
    affected_panel_keys: list[PanelKey] = []
    collapsed_skipped = 0
    visible_patched = 0
    panel_rebuilds = 0
    patch_failed = 0
    for agent, panel_key, _global_idx in patch_plan:
        if panel_key is not None and panel_key not in affected_panel_keys:
            affected_panel_keys.append(panel_key)
        if panel_key is not None and panel_key in collapsed_keys:
            # Collapsed panels hold no rows: only their counts change, via
            # the batched title refresh below. Never expand or rebuild them.
            collapsed_skipped += 1
            continue
        if panel_key is not None and callable(query_one):
            try:
                from ._display_helpers import panel_widget_id_for_key

                widget = query_one(f"#{panel_widget_id_for_key(panel_key)}")
                if len(getattr(widget, "_agents", None) or []) == 0:
                    collapsed_skipped += 1
                    continue
            except Exception:
                pass
        patched = False
        if callable(try_patch):
            try:
                patched = _call_row_patch(try_patch, agent)
            except Exception:
                patched = False
        if patched:
            visible_patched += 1
            continue
        # A visible-row patch fails only for a real reason (such as width
        # growth): rebuild just that panel, never the whole display.
        rebuild_panel = getattr(app, "_refresh_affected_panel_widgets", None)
        if panel_key is not None and callable(rebuild_panel):
            try:
                rebuilt = rebuild_panel({panel_key})
            except Exception:
                rebuilt = False
            if rebuilt:
                panel_rebuilds += 1
            else:
                patch_failed += 1
        else:
            patch_failed += 1

    _refresh_affected_panel_titles(app, panel_index, affected_panel_keys)
    update_info = getattr(app, "_update_agents_info_panel", None)
    if callable(update_info):
        try:
            if callable(query_one):
                query_one("#agent-list-container")
            update_info()
        except Exception:
            pass
    update_header = getattr(app, "_update_agents_header", None)
    if callable(update_header):
        # Machine chip and tab strip: the old patch path never refreshed
        # these, so `,u` left stale counts outside the rows.
        try:
            update_header()
        except Exception:
            pass
    refresh_summary = getattr(app, "_refresh_tribe_summary_only", None)
    if callable(refresh_summary):
        try:
            refresh_summary()
        except Exception:
            pass

    get_selected = getattr(app, "_get_selected_agent", None)
    try:
        selected = get_selected() if callable(get_selected) else None
    except Exception:
        selected = None
    if (
        selected is not None
        and selected.is_clan_container
        and (
            selected.agent_clan,
            selected.agent_clan_generation,
        )
        in affected_clans
    ):
        refresh_detail = getattr(app, "_apply_agent_detail_immediate", None)
        if callable(query_one) and callable(refresh_detail):
            try:
                refresh_detail()
            except Exception:
                pass
    return True, {
        "changed": len(changed),
        "visible_patched": visible_patched,
        "collapsed_skipped": collapsed_skipped,
        "panel_rebuilds": panel_rebuilds,
        "patch_failed": patch_failed,
    }


def _refresh_affected_panel_titles(
    app: Any,
    panel_index: Any,
    affected_panel_keys: list[PanelKey],
) -> None:
    """Refresh each affected panel title once (collapsed panels included)."""
    if not affected_panel_keys:
        return
    title_for_key = getattr(app, "_agent_panel_title_for_key", None)
    set_title = getattr(app, "_set_agent_panel_title", None)
    query_one = getattr(app, "query_one", None)
    if panel_index is None or not callable(title_for_key) or not callable(set_title):
        refresh_all = getattr(app, "_refresh_agent_panel_titles", None)
        if callable(refresh_all) and callable(query_one):
            try:
                refresh_all()
            except Exception:
                pass
        return
    for key in affected_panel_keys:
        try:
            from ._display_helpers import panel_widget_id_for_key

            if not callable(query_one):
                return
            widget = query_one(f"#{panel_widget_id_for_key(key)}")
            title = title_for_key(key, panel_index.slice_for(key).agents)
            set_title(widget, title)
        except Exception:
            continue
