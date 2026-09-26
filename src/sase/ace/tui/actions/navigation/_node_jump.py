"""Identity-based Agents-tab navigation for the Node Finder."""

from __future__ import annotations

from ._agent_reveal import AgentIdentity, AgentRevealFailure
from ._types import NavigationMixinBase


class NodeJumpNavigationMixin(NavigationMixinBase):
    """Reveal a node, clearing a hiding Agents query only when needed."""

    def action_jump_to_node(self) -> None:
        """Open the Agents-tab Node Finder modal on the ``"`` key."""
        exit_jump = getattr(self, "_exit_entry_jump_mode", None)
        if callable(exit_jump):
            exit_jump()
        cancel_member = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member):
            cancel_member()
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return
        from ..agents._node_finder_snapshot import build_node_finder_snapshot

        snapshot = build_node_finder_snapshot(self)
        if not any(row.jumpable for row in snapshot.rows):
            self.notify("No nodes to jump to")  # type: ignore[attr-defined]
            return
        from ...modals import NodeFinderModal, NodeFinderResult

        has_back_fn = getattr(self, "_entry_jump_footer_has_back", None)
        has_back = bool(has_back_fn()) if callable(has_back_fn) else False
        has_back = has_back or bool(getattr(self, "_link_trail", []))

        def _on_dismiss(result: NodeFinderResult | None) -> None:
            if result is None:
                return
            if result.back:
                fast = getattr(self, "action_jump_to_entry_fast", None)
                if callable(fast):
                    fast()
                return
            if result.identity is not None:
                self._jump_to_node_identity(result.identity, name=result.name)

        self.push_screen(  # type: ignore[attr-defined]
            NodeFinderModal(snapshot, has_back=has_back),
            _on_dismiss,
        )

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
        """Reveal ``identity`` through the I and query visibility rungs."""
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False

        reveal = getattr(self, "_try_reveal_agent_row", None)
        if not callable(reveal):
            return False
        failure = reveal(identity)
        if failure is None:
            return True
        if self._should_show_hidden_agents(identity, failure):
            selected_identity = self._selected_agent_identity_for_navigation()

            def _after_hidden_agents_reload() -> None:
                if (
                    getattr(self, "current_tab", None) != "agents"
                    or self._selected_agent_identity_for_navigation()
                    != selected_identity
                ):
                    self.notify(f"Jump to {name} cancelled — you moved")  # type: ignore[attr-defined]
                    return
                self._jump_to_node_identity(identity, name=name)

            show_hidden = getattr(self, "_show_hidden_agents_for_navigation", None)
            if callable(show_hidden):
                show_hidden(_after_hidden_agents_reload)
                self.notify(  # type: ignore[attr-defined]
                    f"Showing agents hidden by I to reach {name} — "
                    "press I to hide them again"
                )
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

    def _should_show_hidden_agents(
        self, identity: AgentIdentity, failure: AgentRevealFailure
    ) -> bool:
        """Whether the first rung can expose a target omitted by ``I``."""
        if failure is not AgentRevealFailure.TARGET_MISSING:
            return False
        if not bool(getattr(self, "hide_non_run_agents", False)):
            return False
        return any(
            getattr(agent, "identity", None) == identity
            for agent in getattr(self, "_hideable_agents", ())
        )

    def _selected_agent_identity_for_navigation(self) -> AgentIdentity | None:
        """Read the selection again after an asynchronous Agents reload."""
        selected = getattr(self, "_get_selected_agent", lambda: None)()
        return getattr(selected, "identity", None)

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
