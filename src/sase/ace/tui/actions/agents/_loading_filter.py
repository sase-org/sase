"""In-memory refiltering and finalize wrappers for agent loading."""

from __future__ import annotations

import asyncio
import logging
from copy import copy
from typing import TYPE_CHECKING, Any, cast

from ._loading_compute import PreparedFinalizePlan
from ._loading_finalize import finalize_agent_list, get_or_parse_agent_query
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


class AgentLoadingFilterMixin(AgentLoadingStateMixin):
    """Methods that re-run in-memory filtering without a disk reload."""

    def _snapshot_agents_for_local_display(self) -> list[Agent]:
        """Return shallow row snapshots for local display diffs."""
        return [copy(agent) for agent in getattr(self, "_agents", [])]

    def _get_or_parse_agent_query(self) -> QueryExpr | None:
        """Return the parsed AST for the active agent search query."""
        return get_or_parse_agent_query(cast(Any, self))

    def _refilter_agents(
        self,
        *,
        prior_pos: int | None = None,
        refresh_content_index: bool = True,
        previous_agents: list[Agent] | None = None,
        refresh_display: bool = True,
    ) -> None:
        """Lightweight agent refresh that skips disk I/O.

        Reuses the cached ``_agents_with_children`` list from the last full
        ``_load_agents()`` call and re-applies only the in-memory pipeline:
        fold filtering, ordering, search, status overrides, panel indices,
        selection restoration, tab-bar counts, and display refresh.

        ``prior_pos`` is the active panel's pre-mutation visible-row
        position of the focused agent — used to restore focus to the agent
        visually below the removed one when the previously selected
        identity is gone (kill / dismiss paths).

        Falls back to scheduling an async load if no full load has run yet —
        callers that need the post-load list synchronously must await the
        scheduled refresh via ``_schedule_agents_async_refresh(on_complete=…)``.
        """
        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)
        # Guard: first load hasn't happened yet — kick off an async load and
        # leave ``_agents`` as-is (empty). Callers that draw the list rely on
        # the existing loading-row mechanism while the async refresh runs.
        if not getattr(self, "_agents_with_children", None) and not getattr(
            self, "_agents_first_load_done", False
        ):
            self._schedule_agents_async_refresh(source="refilter")  # type: ignore[attr-defined]
            return

        on_agents_tab = self.current_tab == "agents"

        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        # Rebuild the pure synthetic clan projection so optimistic status,
        # tag, kill, and dismiss mutations cannot leave a stale container.
        from ...models._agent_tree import project_clan_tree

        self._agents_with_children = project_clan_tree(self._agents_with_children)

        # Start from the cached unfiltered list (already has dismiss/hide applied)
        if previous_agents is None:
            previous_agents = self._snapshot_agents_for_local_display()
        else:
            previous_agents = list(previous_agents)
        self._agents = list(self._agents_with_children)

        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            prior_pos=prior_pos,
            previous_agents=previous_agents,
            refresh_display=refresh_display,
        )
        if refresh_content_index:
            self._schedule_agent_content_search_index_refresh()

    def _schedule_agent_content_search_index_refresh(self) -> None:
        """Refresh the prepared content index for cached agents off-thread."""
        query = getattr(self, "_agent_search_query", "") or ""
        if not query:
            self._agent_content_search_index = None
            self._agent_content_search_refresh_generation = (
                getattr(self, "_agent_content_search_refresh_generation", 0) + 1
            )
            return
        agents = list(getattr(self, "_agents_with_children", []) or [])
        if not agents:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        generation = getattr(self, "_agent_content_search_refresh_generation", 0) + 1
        self._agent_content_search_refresh_generation = generation
        source_generation = getattr(self, "_agent_content_search_source_generation", 0)
        source_identities = tuple(agent.identity for agent in agents)
        fork_cache = getattr(self._agent_content_search_cache, "fork", None)
        if not callable(fork_cache):
            return
        worker_cache = fork_cache()
        prior_task = getattr(self, "_agent_content_search_refresh_task", None)
        if prior_task is not None and not prior_task.done():
            prior_task.cancel()
        task = loop.create_task(
            self._run_agent_content_search_index_refresh(
                worker_cache=worker_cache,
                agents=agents,
                query=query,
                generation=generation,
                source_generation=source_generation,
                source_identities=source_identities,
            )
        )
        self._agent_content_search_refresh_task = task  # type: ignore[attr-defined]

    async def _run_agent_content_search_index_refresh(
        self,
        *,
        worker_cache: Any,
        agents: list[Agent],
        query: str,
        generation: int,
        source_generation: int,
        source_identities: tuple[tuple[AgentType, str, str | None], ...],
    ) -> None:
        """Worker body for cached-agent content index refresh."""
        try:
            index = await asyncio.to_thread(worker_cache.build_index, agents)
        except Exception:
            log.debug("background agent content index refresh failed", exc_info=True)
            return
        if generation != getattr(self, "_agent_content_search_refresh_generation", 0):
            return
        if query != (getattr(self, "_agent_search_query", "") or ""):
            return
        if source_generation != getattr(
            self, "_agent_content_search_source_generation", 0
        ):
            return
        current_agents = list(getattr(self, "_agents_with_children", []) or [])
        if source_identities != tuple(agent.identity for agent in current_agents):
            return

        self._agent_content_search_cache.merge(worker_cache)
        self._agent_content_search_index = index

        on_agents_tab = self.current_tab == "agents"
        selected_identity: tuple[AgentType, str, str | None] | None = None
        if on_agents_tab and self._agents and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        previous_agents = list(self._agents)
        self._agents = current_agents
        self._finalize_agent_list(
            on_agents_tab,
            selected_identity,
            save_unfiltered=False,
            previous_agents=previous_agents,
        )

    def _cancel_pending_content_search_refresh(self) -> None:
        """Cancel any in-flight content-search index refresh (shutdown hook)."""
        task = getattr(self, "_agent_content_search_refresh_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._agent_content_search_refresh_task = None  # type: ignore[attr-defined]

    def _finalize_agent_list(
        self,
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

        Thin wrapper that delegates to
        :func:`._loading_finalize.finalize_agent_list`. Tests drive this
        method directly; production callers reach it via
        :meth:`_apply_loaded_agents_prepared` and :meth:`_refilter_agents`.
        """
        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)
        finalize_agent_list(
            cast(Any, self),
            on_agents_tab,
            selected_identity,
            save_unfiltered=save_unfiltered,
            fold_filter_already_applied=fold_filter_already_applied,
            prior_pos=prior_pos,
            precomputed_plan=precomputed_plan,
            previous_agents=previous_agents,
            refresh_display=refresh_display,
        )
