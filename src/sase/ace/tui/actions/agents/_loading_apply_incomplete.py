"""Incomplete-load and index-repair handling for the prepared-apply path."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ...util.trace import trace_event
from ._loading_apply_history import (
    cache_query_matches_load,
    history_query_key_for_load,
)
from ._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
)
from ._loading_helpers import is_always_visible
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_loader import AgentLoadState


def _agent_index_repair_notice(load_state: AgentLoadState | None) -> str | None:
    """Return the operator-facing repair notice for a load state."""
    if load_state is None or not load_state.repair_recommended:
        return None
    reason = load_state.repair_reason or "unknown"
    return (
        f"Agent index repair recommended: {reason}. "
        "Run `sase agent index status --json`, then `sase agent index gc`."
    )


class AgentLoadingApplyIncompleteMixin(AgentLoadingStateMixin):
    """Methods that reconcile incomplete or repair-flagged loads with the cache."""

    def _preserve_revived_agents_for_incomplete_load(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> bool:
        """Keep revived historical agents visible until Tier 2 reconciles."""
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if not revived_suffixes:
            return False

        loaded_suffixes = {
            agent.raw_suffix
            for agent in prep.filtered_agents
            if agent.raw_suffix is not None
        }
        if load_state is not None and load_state.complete_history:
            revived_suffixes.difference_update(loaded_suffixes)
            return False
        if load_state is None or load_state.complete_history:
            return False

        missing_suffixes = revived_suffixes - loaded_suffixes
        if not missing_suffixes:
            return False

        dismissed_suffixes = {
            raw_suffix
            for _, _, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }
        missing_suffixes -= dismissed_suffixes
        if not missing_suffixes:
            return False

        existing_identities = {agent.identity for agent in prep.filtered_agents}
        preserved: list[Agent] = []
        preserved_suffixes: set[str] = set()
        for agent in self._agents_with_children:
            if agent.raw_suffix not in missing_suffixes:
                continue
            if agent.identity in existing_identities:
                continue
            if agent.identity in self._dismissed_agents:
                continue
            preserved.append(agent)
            existing_identities.add(agent.identity)
            if agent.raw_suffix is not None:
                preserved_suffixes.add(agent.raw_suffix)

        # Fall back to the dismissed-bundle cache for revived suffixes that
        # never landed in ``_agents_with_children`` (e.g. long-dismissed
        # bundles revived from the archive). The revive flow hydrates those
        # bundle agents into ``_dismissed_agent_objects`` before calling the
        # loader, so the data is on hand for first-paint visibility.
        remaining_suffixes = missing_suffixes - preserved_suffixes
        if remaining_suffixes:
            for agent in self._dismissed_agent_objects:
                if agent.raw_suffix not in remaining_suffixes:
                    continue
                if agent.identity in existing_identities:
                    continue
                if agent.identity in self._dismissed_agents:
                    continue
                preserved.append(agent)
                existing_identities.add(agent.identity)

        if not preserved:
            return False

        prep.filtered_agents = [*prep.filtered_agents, *preserved]
        prep.has_always_visible = any(
            is_always_visible(a) for a in prep.filtered_agents
        )
        prep.hideable_agents = [
            agent for agent in prep.filtered_agents if not is_always_visible(agent)
        ]
        return True

    def _merge_incomplete_load_after_complete_history(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> None:
        """Compatibility hook for the incomplete Tier 1 merge step."""
        merge_incomplete_load_after_complete_history(
            prep,
            self._make_prepared_apply_snapshot(
                on_agents_tab=False,
                selected_identity=None,
                load_state=load_state,
            ),
        )

    def _note_empty_incomplete_apply_ignored(
        self,
        load_state: AgentLoadState | None,
    ) -> None:
        """Trace a same-query bounded zero that the merge keeps out of the cache.

        The bounded zero patches over the cache instead of replacing it; one
        revalidated load then confirms whether the rows really are gone.
        """
        if load_state is None or load_state.returned_count != 0:
            self._agents_empty_ignored_revalidated = False
            return
        if (
            load_state.complete_history
            or not load_state.bounded_prefix
            or not getattr(self, "_agents_with_children", None)
            or not cache_query_matches_load(self, load_state)
        ):
            return
        trace_event(
            "agents.empty_incomplete_apply_ignored",
            reason="empty_incomplete_apply_ignored",
            cached=len(self._agents_with_children),
            history_query_key=repr(history_query_key_for_load(self, load_state)),
            has_more=load_state.has_more,
        )
        if getattr(self, "_agents_empty_ignored_revalidated", False):
            return
        self._agents_empty_ignored_revalidated = True
        cast("Any", self)._schedule_agents_async_refresh(
            source="empty_incomplete_revalidate",
            revalidate_index=True,
        )

    def _maybe_notify_agent_index_repair(
        self, load_state: AgentLoadState | None
    ) -> None:
        """Show a one-shot visible repair notice when Tier 1 diagnostics ask."""
        notice = _agent_index_repair_notice(load_state)
        if notice is None:
            self._agents_index_repair_notice_key = None
            return
        key = (
            load_state.repair_reason if load_state is not None else None,
            load_state.index_error if load_state is not None else None,
        )
        if key == getattr(self, "_agents_index_repair_notice_key", None):
            return
        self._agents_index_repair_notice_key = key
        self.notify(notice, severity="warning")  # type: ignore[attr-defined]
