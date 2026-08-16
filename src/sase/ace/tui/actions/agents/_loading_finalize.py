"""Post-load agent list finalization pipeline.

The finalize pipeline runs on the UI thread after :func:`_compute_apply_loaded_agents`
hands back its prepared snapshot. It applies fold filtering, the agent
search query, status overrides, panel indices, selection restoration,
group-registry GC, tab-bar counts, and the final display refresh.

The implementation lives here as a free function so the mixin in
:mod:`._loading` can stay below ~500 lines while still exposing the
``_finalize_agent_list`` method that tests drive directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sase.core.time import local_now

from ._loading_compute import PreparedFinalizePlan
from ._fold_scope import reconcile_panel_fold_registries
from ._loading_helpers import (
    build_question_answer_family_index,
    should_clear_loaded_agent_status_override,
)
from ...util.trace import tui_trace

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ._loading import AgentLoadingMixin

log = logging.getLogger(__name__)


def _sync_unread_completed_agents(app: AgentLoadingMixin, on_agents_tab: bool) -> None:
    """Reconcile Agents-tab unread rows with active completion notifications.

    The notification store is the source of truth: a row is unread iff its
    matching completion notification is still active (not dismissed) and
    manual ``U`` marks survive on rows that lack a notification.

    Stale identities (agents no longer loaded) are pruned. Newly-terminal
    rows are picked up by the notification-projection reconcile step rather
    than a status transition; a focused row remains unread until the user
    intentionally enters it again through a selection/navigation event.
    """
    unread_ids = getattr(app, "_unread_completed_agent_ids", None)
    if unread_ids is None:
        unread_ids = set()
        app._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
    manual_ids = getattr(app, "_manual_unread_agent_ids", None)
    if manual_ids is None:
        manual_ids = set()
        app._manual_unread_agent_ids = manual_ids  # type: ignore[attr-defined]

    from ._notification_unread_projection import loaded_real_agent_roster
    from ...models.agent_nodes import (
        agent_node_projection_index,
        normalize_agent_node_identities,
    )

    loaded_agents = loaded_real_agent_roster(app)
    node_index = agent_node_projection_index(loaded_agents)
    prior_unread_ids = set(unread_ids)
    prior_manual_ids = set(manual_ids)
    unread_ids.clear()
    unread_ids.update(
        normalize_agent_node_identities(
            prior_unread_ids,
            node_index,
        )
    )
    manual_ids.clear()
    manual_ids.update(
        normalize_agent_node_identities(
            prior_manual_ids,
            node_index,
        )
    )

    snapshot = getattr(app, "_notification_snapshot_cache", None)
    if snapshot is None:
        schedule_refresh = getattr(app, "_schedule_notification_snapshot_refresh", None)
        if callable(schedule_refresh):
            schedule_refresh()
    else:
        reconcile = getattr(
            app, "_reconcile_unread_from_completion_notifications", None
        )
        if callable(reconcile):
            reconcile(snapshot.notifications)

    app._agent_display_status_by_identity = {  # type: ignore[attr-defined]
        agent.identity: agent.status for agent in loaded_agents
    }


def get_or_parse_agent_query(app: AgentLoadingMixin) -> QueryExpr | None:
    """Return the parsed AST for the active agent search query.

    Returns ``None`` when the query is empty or fails to parse — the
    caller treats both as "no filter applied". The parsed AST is cached
    on ``app._agent_query_cache`` keyed by the raw query string so
    re-renders skip the parse. Parse failures emit a transient toast
    and persist the error message on ``app`` for the modal to surface.
    """
    from ....agent_query import AgentQueryParseError, parse_agent_query

    raw = getattr(app, "_agent_search_query", "") or ""
    if not raw:
        app._agent_query_cache = None
        app._agent_query_parse_error = None
        return None

    cached = getattr(app, "_agent_query_cache", None)
    if cached is not None and cached[0] == raw:
        return cached[1]

    try:
        parsed = parse_agent_query(raw)
    except AgentQueryParseError as e:
        msg = str(e)
        app._agent_query_parse_error = msg
        # Cache the failure to avoid re-parsing the bad query each render.
        app._agent_query_cache = (raw, None)
        try:
            app.notify(  # type: ignore[attr-defined]
                f"Bad query: {msg}", severity="warning"
            )
        except Exception:
            log.warning("agent query parse error: %s", msg)
        return None

    app._agent_query_parse_error = None
    app._agent_query_cache = (raw, parsed)
    return parsed


def _surface_query_parse_error_from_plan(
    app: AgentLoadingMixin,
    plan: PreparedFinalizePlan,
) -> None:
    """Mirror the UI-thread parse-error behavior from a precomputed plan."""
    raw = plan.query.raw_query
    if not raw:
        app._agent_query_cache = None
        app._agent_query_parse_error = None
        return
    if plan.query.parse_error is not None:
        msg = plan.query.parse_error
        app._agent_query_parse_error = msg
        app._agent_query_cache = (raw, None)
        try:
            app.notify(  # type: ignore[attr-defined]
                f"Bad query: {msg}", severity="warning"
            )
        except Exception:
            log.warning("agent query parse error: %s", msg)
        return
    app._agent_query_parse_error = None
    app._agent_query_cache = (raw, plan.query.parsed_ast)


def _apply_finalize_plan(
    app: AgentLoadingMixin,
    on_agents_tab: bool,
    selected_identity: tuple[AgentType, str, str | None] | None,
    plan: PreparedFinalizePlan,
    *,
    prior_pos: int | None,
    previous_agents: list[Agent] | None,
    refresh_display: bool,
) -> None:
    """UI-thread half of the precomputed-plan apply path."""
    _surface_query_parse_error_from_plan(app, plan)

    # Install the post-query agent list and prune the content cache to match.
    app._agents = list(plan.query.filtered_agents)
    app._agent_content_search_cache.prune(app._agents)

    # Apply status overrides + clean stale entries based on the worker plan.
    overrides_by_identity = dict(plan.overrides.overrides_to_apply)
    for agent in app._agents:
        override = overrides_by_identity.get(agent.identity)
        if override is not None:
            agent.status = override
    for identity in plan.overrides.cleared_identities:
        app._agent_status_overrides.pop(identity, None)
        app._agent_pre_question_status.pop(identity, None)

    saved_idx = plan.selection.restored_idx
    identity_restored = plan.selection.identity_restored

    if (
        on_agents_tab
        and prior_pos is not None
        and selected_identity is not None
        and not identity_restored
    ):
        app.current_idx = saved_idx
        app._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]
    else:
        if app._agents:
            new_idx = min(saved_idx, len(app._agents) - 1)
        else:
            new_idx = 0
        if on_agents_tab:
            app.current_idx = new_idx
        else:
            app._agents_last_idx = new_idx
            if app._agents and 0 <= new_idx < len(app._agents):
                app._agents_last_identity = app._agents[new_idx].identity  # type: ignore[attr-defined]
            else:
                app._agents_last_identity = None  # type: ignore[attr-defined]

    _sync_unread_completed_agents(app, on_agents_tab)

    reconcile_panel_fold_registries(app, plan.panel_group_keys)

    if on_agents_tab and refresh_display:
        with tui_trace("agents.final_display_refresh", agents=len(app._agents)):
            incremental_refresh = getattr(
                app,
                "_refresh_agents_display_after_finalize",
                None,
            )
            if callable(incremental_refresh):
                incremental_refresh(
                    previous_agents=previous_agents,
                    defer_detail=True,
                )
            else:
                app._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=True,
                    defer_detail=True,
                )


def finalize_agent_list(
    app: AgentLoadingMixin,
    on_agents_tab: bool,
    selected_identity: tuple[AgentType, str, str | None] | None,
    *,
    save_unfiltered: bool,
    fold_filter_already_applied: bool = False,
    prior_pos: int | None = None,
    precomputed_plan: PreparedFinalizePlan | None = None,
    previous_agents: list[Agent] | None = None,
    refresh_display: bool = True,
) -> None:
    """Shared post-processing pipeline for agent list finalization.

    Applies fold filtering, custom ordering, search filter, status
    overrides, panel indices, selection restoration, tab-bar counts,
    and display refresh.

    Args:
        app: The :class:`AgentLoadingMixin` instance owning the agent
            list and related panel state.
        on_agents_tab: Whether the agents tab is currently active.
        selected_identity: Identity of the previously selected agent.
        save_unfiltered: If True, save ``_agents_with_children`` before
            fold filtering (used by full load, not refilter).
        prior_pos: Pre-mutation visible-row position of the previously
            focused agent on the active panel. Only used when the
            selected identity is gone (kill / dismiss); routes through
            ``_restore_focus_after_removal`` so focus lands on the
            agent visually below the removed one.
    """
    # A fast post-first-paint fold-state load gets one chance to become the
    # baseline before the first real Agents projection reconciles and renders.
    # This is a pure in-memory import; the loader's file/JSON work ran in its
    # independent worker and never gates this boundary.
    install_fold_state = getattr(
        app,
        "_maybe_install_agents_fold_state_before_finalize",
        None,
    )
    if callable(install_fold_state):
        install_fold_state()

    if save_unfiltered:
        # Save unfiltered list (with children) for bundle/dismiss operations
        # that need to find child steps even when fold state is COLLAPSED.
        app._agents_with_children = list(app._agents)
        app._agent_content_search_source_generation = (
            getattr(app, "_agent_content_search_source_generation", 0) + 1
        )
    if not fold_filter_already_applied:
        # Apply fold-state filtering for workflow children.
        from ...models import filter_agents_by_fold_state

        with tui_trace("agents.fold_filtering", count=len(app._agents)):
            app._agents, app._fold_counts = filter_agents_by_fold_state(
                app._agents, app._fold_manager
            )

    if precomputed_plan is not None:
        _apply_finalize_plan(
            app,
            on_agents_tab,
            selected_identity,
            precomputed_plan,
            prior_pos=prior_pos,
            previous_agents=previous_agents,
            refresh_display=refresh_display,
        )
        return

    # Apply agent search filter via the structured agent query language.
    # The haystack includes metadata fields plus each agent's cached
    # prompt/reply content — see ``AgentContentSearchCache``. Content
    # reads only happen when a query is active. Parse errors are
    # non-fatal: surface a toast and skip filtering for this render.
    parsed_ast = get_or_parse_agent_query(app)
    if parsed_ast is not None:
        from ....agent_query import evaluate_agent_query

        content_index = getattr(app, "_agent_content_search_index", None)
        now = local_now()

        def _matches(agent: Agent) -> bool:
            return evaluate_agent_query(
                parsed_ast, agent, now=now, content_cache=content_index
            )

        from ...models._agent_tree import filter_tree_rows

        app._agents = filter_tree_rows(app._agents, _matches)
        # Release cache entries for agents no longer in the list so
        # memory stays bounded across many refresh cycles.
        app._agent_content_search_cache.prune(app._agents)

    # Apply status overrides (PLAN/PLAN APPROVED/QUESTION), clearing entries
    # that the fresh loader state has overtaken.
    loaded_identities = {a.identity for a in app._agents}
    family_index = build_question_answer_family_index(app._agents)
    for agent in app._agents:
        override = app._agent_status_overrides.get(agent.identity)
        if override is None:
            continue
        if should_clear_loaded_agent_status_override(agent, override, family_index):
            app._agent_status_overrides.pop(agent.identity, None)
            app._agent_pre_question_status.pop(agent.identity, None)
        else:
            agent.status = override

    # Clean overrides for agents that no longer exist in the loaded list
    for identity in list(app._agent_status_overrides):
        if identity not in loaded_identities:
            app._agent_status_overrides.pop(identity, None)
            app._agent_pre_question_status.pop(identity, None)

    # Calculate the new index
    # Use current_idx when on agents tab, otherwise use saved _agents_last_idx
    saved_idx = app.current_idx if on_agents_tab else app._agents_last_idx

    # Identity-preserving restoration via the shared helper. This deliberately
    # replaces the old "search-then-fall-through-to-saved_idx" path so the
    # neighbor-based fallback (clamped prior visual row) wins when the agent
    # disappears — instead of leaving the cursor at whatever stale numeric
    # index happened to be in saved_idx and then drifting downstream.
    from ...util.selection import restore_selection_by_identity

    restored_idx = restore_selection_by_identity(
        app._agents,
        prior_identity=selected_identity,
        prior_visual_row=saved_idx,
        identity_fn=lambda agent: agent.identity,
    )
    identity_restored = (
        selected_identity is not None
        and 0 <= restored_idx < len(app._agents)
        and app._agents[restored_idx].identity == selected_identity
    )
    saved_idx = restored_idx

    # When the previously selected identity is gone (kill / dismiss),
    # re-anchor focus to the agent that now occupies the same visible
    # row the killed one had.  Only the on-agents-tab branch needs this
    # — the saved-idx branch is just a stash for tab switches.
    if (
        on_agents_tab
        and prior_pos is not None
        and selected_identity is not None
        and not identity_restored
    ):
        app.current_idx = saved_idx
        app._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]
    else:
        # Clamp to valid bounds
        if app._agents:
            new_idx = min(saved_idx, len(app._agents) - 1)
        else:
            new_idx = 0

        # Only modify current_idx if we're on the agents tab
        # Otherwise, update the saved position for when user switches to agents tab
        if on_agents_tab:
            app.current_idx = new_idx
        else:
            app._agents_last_idx = new_idx
            # Keep the off-tab identity snapshot consistent with the row
            # we'd land on when the user tabs back. Without this, a later
            # rebuild on this same tab would see a stale identity that no
            # longer matches ``_agents_last_idx``.
            if app._agents and 0 <= new_idx < len(app._agents):
                app._agents_last_identity = app._agents[new_idx].identity  # type: ignore[attr-defined]
            else:
                app._agents_last_identity = None  # type: ignore[attr-defined]

    _sync_unread_completed_agents(app, on_agents_tab)

    # Garbage-collect collapse entries for groups that vanished after
    # the latest fold/search/filter pipeline so a re-appearing group
    # key never inherits stale collapse state.  ``_grouping_mode`` is
    # the active L0 layout — keys for inactive modes live in their
    # own registry slot and stay untouched.
    from ...models.agent_group_fold import enumerate_panel_group_keys

    grouping_mode = getattr(app, "_grouping_mode", None)
    if grouping_mode is None:
        from ...models.agent_groups import GroupingMode

        grouping_mode = GroupingMode.STANDARD
    reconcile_panel_fold_registries(
        app,
        enumerate_panel_group_keys(
            app._agents,
            mode=grouping_mode,
            merged=bool(getattr(app, "_agent_panels_grouped", False)),
        ),
    )

    # Only refresh display if on agents tab
    if on_agents_tab and refresh_display:
        with tui_trace("agents.final_display_refresh", agents=len(app._agents)):
            incremental_refresh = getattr(
                app,
                "_refresh_agents_display_after_finalize",
                None,
            )
            if callable(incremental_refresh):
                incremental_refresh(
                    previous_agents=previous_agents,
                    defer_detail=True,
                )
            else:
                app._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=True,
                    defer_detail=True,
                )
