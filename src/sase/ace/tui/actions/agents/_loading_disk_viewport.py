"""Viewport and stale-query helpers for agent disk loads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ...data_providers import AgentsViewport
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models.agent_loader import AgentLoadState

_DEFAULT_AGENTS_VISIBLE_ROWS = 40
_MIN_AGENTS_VISIBLE_ROWS = 12
_MAX_AGENTS_VISIBLE_ROWS = 80


def agents_viewport_for_load(app: Any) -> AgentsViewport | None:
    """Capture the growing-prefix viewport for an Agents-tab provider read.

    Returns ``None`` for the one-shot startup prefix-completion refresh so
    the provider issues an unwindowed cached read.
    """

    if getattr(app, "_agents_refresh_scheduled_prefix_completion", False) or getattr(
        app, "_agents_refresh_active_prefix_completion", False
    ):
        return None

    current_tab = getattr(app, "current_tab", "")
    index_source = (
        getattr(app, "current_idx", 0)
        if current_tab == "agents"
        else getattr(app, "_agents_last_idx", 0)
    )
    try:
        start_row = max(0, int(index_source))
    except (TypeError, ValueError):
        start_row = 0

    size = getattr(app, "size", None)
    height = getattr(size, "height", None)
    try:
        visible_rows = (
            int(height) - 8 if height is not None else _DEFAULT_AGENTS_VISIBLE_ROWS
        )
    except (TypeError, ValueError):
        visible_rows = _DEFAULT_AGENTS_VISIBLE_ROWS
    visible_rows = max(
        _MIN_AGENTS_VISIBLE_ROWS,
        min(_MAX_AGENTS_VISIBLE_ROWS, visible_rows),
    )
    return AgentsViewport(
        start_row=start_row,
        visible_rows=visible_rows,
        prefetch_rows=visible_rows * 2,
    )


def agents_viewport_request_key(
    search_query: str,
    viewport: AgentsViewport | None,
) -> tuple[object, ...]:
    """Return the in-flight request identity for a provider read."""

    if viewport is None:
        return (search_query, None)
    return (
        search_query,
        viewport.start_row,
        viewport.visible_rows,
        viewport.prefetch_rows,
    )


def current_agents_history_query_key(app: Any) -> tuple[str, str]:
    """Return the committed-query key for the app's current Agents query."""
    from ...models.agent_live_query_engine import agents_history_query_key

    return agents_history_query_key(getattr(app, "_agent_search_query", "") or "")


def agent_load_query_is_stale(app: Any, load_state: AgentLoadState | None) -> bool:
    """Return whether an async load belongs to an obsolete committed query."""
    load_key = getattr(load_state, "history_query_key", None)
    if load_key is None:
        return False
    return load_key != current_agents_history_query_key(app)


def reschedule_stale_agent_query_load(
    app: Any,
    *,
    source: str,
    full_history: bool,
    full_history_reason: str | None,
    index_freshness: Literal["revalidate", "cached"],
    complete_prefix: bool = False,
) -> None:
    """Schedule a replacement read for the current query after discarding stale data."""
    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if not callable(schedule_refresh):
        return
    schedule_refresh(
        source=source,
        full_history=full_history,
        full_history_reason=(
            full_history_reason or "stale_query_retry" if full_history else None
        ),
        revalidate_index=index_freshness == "revalidate",
        complete_prefix=complete_prefix,
    )


class AgentLoadingDiskViewportMixin(AgentLoadingStateMixin):
    """Viewport expansion behavior for bounded agent disk reads."""

    def _maybe_schedule_agents_viewport_expansion(
        self,
        *,
        source: str = "viewport",
    ) -> None:
        """Request a larger bounded prefix when focus enters the prefetch band."""

        load_state = getattr(self, "_agent_load_state", None)
        if (
            load_state is None
            or not load_state.bounded_prefix
            or not load_state.has_more
        ):
            return
        requested_limit = load_state.requested_limit
        if requested_limit is None:
            return
        viewport = agents_viewport_for_load(self)
        if viewport is None:
            return
        if viewport.requested_limit <= requested_limit:
            return
        if self.current_idx < max(0, requested_limit - viewport.prefetch_rows):
            return
        last_requested = getattr(self, "_agents_viewport_last_requested_limit", 0)
        if viewport.requested_limit <= last_requested:
            return
        self._agents_viewport_last_requested_limit = viewport.requested_limit
        schedule_refresh = getattr(self, "_schedule_agents_async_refresh", None)
        if callable(schedule_refresh):
            schedule_refresh(source=source)
