"""History-query and reconcile predicates for the prepared-apply path."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ...models.agent_live_query_engine import AgentsHistoryQueryKey
    from ...models.agent_loader import AgentLoadState


def history_query_key_for_load(
    app: object,
    load_state: AgentLoadState | None,
) -> AgentsHistoryQueryKey:
    """Return the committed-query key that the incoming load covers."""

    load_key = getattr(load_state, "history_query_key", None)
    if load_key is not None:
        return cast("AgentsHistoryQueryKey", load_key)
    from ...models.agent_live_query_engine import agents_history_query_key

    return agents_history_query_key(getattr(app, "_agent_search_query", "") or "")


def has_complete_history_for_load_query(
    app: object,
    load_state: AgentLoadState | None,
) -> bool:
    """Return whether cached full history belongs to this load's query key."""

    complete_key = getattr(app, "_agents_complete_history_query_key", None)
    if complete_key is None:
        # Compatibility for tests and older in-memory app fakes that set the
        # historical boolean directly without the keyed latch.
        return bool(getattr(app, "_agents_seen_complete_history", False))
    return complete_key == history_query_key_for_load(app, load_state)


def cache_query_matches_load(
    app: object,
    load_state: AgentLoadState | None,
) -> bool:
    """Return whether the cached roster was applied under this load's query."""

    applied_key = getattr(app, "_agents_applied_query_key", None)
    if applied_key is None:
        return True
    return applied_key == history_query_key_for_load(app, load_state)


def should_arm_full_history_reconcile(
    load_state: AgentLoadState | None,
    *,
    history_complete_for_query: bool = False,
) -> bool:
    """Return whether this load state should arm a deferred Tier 2 reconcile."""
    if load_state is None or not load_state.needs_full_history_reconcile:
        return False
    if load_state.repair_recommended:
        return True
    if load_state.query_incomplete:
        return not history_complete_for_query
    return not load_state.complete_visible_inbox and not load_state.used_artifact_index
