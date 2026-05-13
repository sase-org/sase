"""In-memory refiltering and finalize wrappers for agent loading."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ._loading_finalize import finalize_agent_list, get_or_parse_agent_query
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models.agent import AgentType


class AgentLoadingFilterMixin(AgentLoadingStateMixin):
    """Methods that re-run in-memory filtering without a disk reload."""

    def _get_or_parse_agent_query(self) -> QueryExpr | None:
        """Return the parsed AST for the active agent search query."""
        return get_or_parse_agent_query(cast(Any, self))

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        """Lightweight agent refresh that skips disk I/O.

        Reuses the cached ``_agents_with_children`` list from the last full
        ``_load_agents()`` call and re-applies only the in-memory pipeline:
        fold filtering, ordering, search, status overrides, panel indices,
        selection restoration, tab-bar counts, and display refresh.

        ``prior_pos`` is the active panel's pre-mutation visible-row
        position of the focused agent — used to restore focus to the agent
        visually below the removed one when the previously selected
        identity is gone (kill / dismiss paths).

        Falls back to ``_load_agents()`` if no full load has run yet.
        """
        # Guard: first load hasn't happened yet
        if not self._agents_with_children:
            self._load_agents()
            return

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        # Start from the cached unfiltered list (already has dismiss/hide applied)
        self._agents = list(self._agents_with_children)

        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            prior_pos=prior_pos,
        )

    def _finalize_agent_list(
        self,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        *,
        save_unfiltered: bool,
        prior_pos: int | None = None,
    ) -> None:
        """Shared post-processing pipeline for agent list finalization.

        Thin wrapper that delegates to
        :func:`._loading_finalize.finalize_agent_list`. Tests drive this
        method directly; production callers reach it via
        :meth:`_apply_loaded_agents_prepared` and :meth:`_refilter_agents`.
        """
        finalize_agent_list(
            cast(Any, self),
            on_agents_tab,
            selected_identity,
            save_unfiltered=save_unfiltered,
            prior_pos=prior_pos,
        )
