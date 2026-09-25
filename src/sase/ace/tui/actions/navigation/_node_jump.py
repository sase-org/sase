"""Identity-based Agents-tab navigation for the Node Finder."""

from __future__ import annotations

from ._agent_reveal import AgentIdentity, AgentRevealFailure
from ._types import NavigationMixinBase


class NodeJumpNavigationMixin(NavigationMixinBase):
    """Reveal a node, clearing a hiding Agents query only when needed."""

    def _clear_agents_query_for_navigation(self) -> str | None:
        """Clear an active Agents query and record its reversible transition."""
        query = getattr(self, "_agent_search_query", "") or ""
        if not query.strip():
            return None

        from ...models.agent_live_query_engine import agents_unified_query_enabled

        if agents_unified_query_enabled():
            close_session = getattr(self, "_close_agents_filter_session", None)
            if callable(close_session):
                close_session()
            record = getattr(self, "_record_agents_live_query_transition", None)
            if callable(record):
                record(query, "")

        commit = getattr(self, "_record_explicit_agents_query_commit", None)
        if callable(commit):
            commit("")
        else:
            self._agent_search_query = ""  # type: ignore[attr-defined]

        refilter = getattr(self, "_refilter_agents", None)
        if callable(refilter):
            try:
                refilter(refresh_display=False)
            except TypeError:
                refilter()
        refresh = getattr(self, "_schedule_agents_async_refresh", None)
        if callable(refresh):
            refresh(source="filter")
        return query

    def _jump_to_node_identity(self, identity: AgentIdentity, *, name: str) -> bool:
        """Reveal ``identity``, clearing only a query that filters it out."""
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False

        reveal = getattr(self, "_try_reveal_agent_row", None)
        if not callable(reveal):
            return False
        failure = reveal(identity)
        if failure is None:
            return True
        query = getattr(self, "_agent_search_query", "") or ""
        if failure is AgentRevealFailure.TARGET_FILTERED and query.strip():
            cleared = self._clear_agents_query_for_navigation()
            failure = reveal(identity)
            if failure is None:
                self._notify_query_clear(name, cleared or query)
                return True

        notify = getattr(self, "_notify_member_reveal_failure", None)
        if callable(notify):
            notify(failure, subject="Node")
        return False

    def _notify_query_clear(self, name: str, query: str) -> None:
        """Toast the one persistent view-state mutation made by this ladder."""
        from ...models.agent_live_query_engine import agents_unified_query_enabled

        quoted = _truncate_query(query)
        if agents_unified_query_enabled():
            previous, next_ = self._agents_query_history_keys()
            message = (
                f"Cleared Agents query ‹{quoted}› to reach {name} — "
                f"{previous} then {next_} restores it"
            )
        else:
            message = f"Cleared Agents query ‹{quoted}› to reach {name}"
        self.notify(message)  # type: ignore[attr-defined]

    def _agents_query_history_keys(self) -> tuple[str, str]:
        """Format the active configurable history keys for the query-clear toast."""
        from ...keymaps import key_display_name

        keymaps = getattr(getattr(self, "_keymap_registry", None), "app", None)
        filter_key = getattr(keymaps, "agents_filters", "f")
        previous = getattr(keymaps, "prev_query", "^")
        return key_display_name(filter_key), key_display_name(previous)


def _truncate_query(query: str, *, limit: int = 40) -> str:
    """Keep a query-clear notification legible without hiding its identity."""
    return query if len(query) <= limit else f"{query[: limit - 1]}…"


__all__ = ["NodeJumpNavigationMixin"]
