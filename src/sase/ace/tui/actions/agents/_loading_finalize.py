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
from collections.abc import MutableMapping
from datetime import datetime
from typing import TYPE_CHECKING

from ._loading_helpers import DISMISSABLE_STATUSES

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ._loading import AgentLoadingMixin

log = logging.getLogger(__name__)


def apply_transient_status_overrides(
    agents: list[Agent],
    status_overrides: MutableMapping[tuple[AgentType, str, str | None], str],
    pre_question_status: MutableMapping[tuple[AgentType, str, str | None], str | None],
) -> tuple[tuple[AgentType, str, str | None], ...]:
    """Apply UI-owned status overrides and prune entries that no longer apply.

    These overrides are transient app state from notification actions, not
    loader facts. The helper is intentionally data-only so the finalizer can
    keep the policy isolated without coupling the Rust composer to TUI state.
    """
    loaded_identities = {a.identity for a in agents}
    cleared: list[tuple[AgentType, str, str | None]] = []

    for agent in agents:
        if agent.status in DISMISSABLE_STATUSES:
            if (
                agent.identity in status_overrides
                or agent.identity in pre_question_status
            ):
                cleared.append(agent.identity)
            status_overrides.pop(agent.identity, None)
            pre_question_status.pop(agent.identity, None)
        elif agent.identity in status_overrides:
            agent.status = status_overrides[agent.identity]

    for identity in list(status_overrides):
        if identity not in loaded_identities:
            cleared.append(identity)
            status_overrides.pop(identity, None)
            pre_question_status.pop(identity, None)

    return tuple(cleared)


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


def finalize_agent_list(
    app: AgentLoadingMixin,
    on_agents_tab: bool,
    selected_identity: tuple[AgentType, str, str | None] | None,
    *,
    save_unfiltered: bool,
    prior_pos: int | None = None,
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
    # Apply fold-state filtering for workflow children
    from ...models import filter_agents_by_fold_state

    if save_unfiltered:
        # Save unfiltered list (with children) for bundle/dismiss operations
        # that need to find child steps even when fold state is COLLAPSED.
        app._agents_with_children = list(app._agents)
    app._agents, app._fold_counts = filter_agents_by_fold_state(
        app._agents, app._fold_manager
    )

    # Apply agent search filter via the structured agent query language.
    # The haystack includes metadata fields plus each agent's cached
    # prompt/reply content — see ``AgentContentSearchCache``. Content
    # reads only happen when a query is active. Parse errors are
    # non-fatal: surface a toast and skip filtering for this render.
    parsed_ast = get_or_parse_agent_query(app)
    if parsed_ast is not None:
        from ....agent_query import evaluate_agent_query

        content_cache = app._agent_content_search_cache
        now = datetime.now()

        def _matches(agent: Agent) -> bool:
            return evaluate_agent_query(
                parsed_ast, agent, now=now, content_cache=content_cache
            )

        # Collect identities of matching parents so children stay visible
        matching_parent_names: set[str] = set()
        for agent in app._agents:
            if not agent.is_workflow_child and _matches(agent):
                matching_parent_names.add(agent.agent_name or agent.cl_name)

        app._agents = [
            a
            for a in app._agents
            if (
                _matches(a)
                # Or child of a matching parent (preserve hierarchy)
                or (
                    a.is_workflow_child
                    and (a.agent_name or a.cl_name) in matching_parent_names
                )
            )
        ]
        # Release cache entries for agents no longer in the list so
        # memory stays bounded across many refresh cycles.
        content_cache.prune(app._agents)

    # Apply transient notification-driven status overrides.
    apply_transient_status_overrides(
        app._agents,
        app._agent_status_overrides,
        app._agent_pre_question_status,
    )

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

    # Garbage-collect collapse entries for groups that vanished after
    # the latest fold/search/filter pipeline so a re-appearing group
    # key never inherits stale collapse state.  ``_grouping_mode`` is
    # the active L0 layout — keys for inactive modes live in their
    # own registry slot and stay untouched.
    from ...models.agent_groups import enumerate_group_keys

    grouping_mode = getattr(app, "_grouping_mode", None)
    if grouping_mode is None:
        from ...models.agent_groups import GroupingMode

        grouping_mode = GroupingMode.STANDARD
    app._group_fold_registry.clear_unknown(
        enumerate_group_keys(app._agents, mode=grouping_mode)
    )

    # Update the running agent counts on the tab bar.
    # Exclude workflow children -- they are sub-steps of a parent agent
    # and should not inflate the top-level running count.
    # All counts use the final displayed list (self._agents) rather than
    # the pre-filter always_visible/all_agents -- fold-state filtering
    # removes workflow parents whose children are all hidden steps, so
    # the pre-filter lists can contain agents not shown in the UI.
    manual_running = sum(
        1
        for a in app._agents
        if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
    )
    if app._has_always_visible:
        hidden_running = sum(
            1
            for a in app._hideable_agents
            if a.status not in DISMISSABLE_STATUSES and not a.is_workflow_child
        )
    else:
        hidden_running = 0
    done_visible = sum(
        1
        for a in app._agents
        if a.status in DISMISSABLE_STATUSES and not a.is_workflow_child
    )
    from ...widgets import TabBar

    try:
        tab_bar = app.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        tab_bar.update_agents_count(
            manual_running,
            hidden_running,
            show_hidden=not app.hide_non_run_agents,
            done_count=done_visible,
        )
    except Exception:
        pass

    # Only refresh display if on agents tab
    if on_agents_tab:
        app._refresh_agents_display(  # type: ignore[attr-defined]
            list_changed=True,
            defer_detail=True,
        )
        # Refresh the file panel for the now-selected agent. Silently
        # skip when nothing is selected or the agent is dismissable so
        # auto-refresh doesn't spam notifications.
        selected_agent = app._get_selected_agent()  # type: ignore[attr-defined]
        if (
            selected_agent is not None
            and selected_agent.status not in DISMISSABLE_STATUSES
        ):
            from ...widgets import AgentDetail

            try:
                agent_detail = app.query_one(  # type: ignore[attr-defined]
                    "#agent-detail-panel", AgentDetail
                )
            except Exception:
                agent_detail = None
            if agent_detail is not None:
                agent_detail.refresh_current_file(selected_agent)
