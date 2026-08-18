"""Filter actions for the Agents tab."""

from __future__ import annotations


class AgentFilterActionsMixin:
    """Mixin providing agent visibility and query filter actions."""

    hide_non_run_agents: bool
    _agent_search_query: str
    _agent_search_query_seeded: bool

    def _toggle_hide_non_run_agents(self) -> None:
        """Toggle visibility of non-run agents and refresh the display."""
        self.hide_non_run_agents = not self.hide_non_run_agents
        self._refilter_agents()  # type: ignore[attr-defined]
        # The hide filter is applied by the disk-load pipeline, not by the
        # in-memory refilter: the cached ``_agents_with_children`` list was
        # built with the previous flag value, so a reload is required for
        # the toggle to take effect.
        self._schedule_agents_async_refresh(source="filter")  # type: ignore[attr-defined]

    def _edit_agent_search_query(self) -> None:
        """Open modal to edit the agent search/filter query."""
        from ....agent_query import parse_agent_query
        from ...modals import QueryEditModal

        def on_dismiss(new_query: str | None) -> None:
            if new_query is None:
                return
            self._agent_search_query = new_query
            self._agent_search_query_seeded = False
            self._refilter_agents()  # type: ignore[attr-defined]

        def _validator(value: str) -> None:
            if value:
                parse_agent_query(value)

        hint = (
            "status:foo  cl:bar  project:baz  age>2h  attention:true  "
            "AND/OR/NOT  (?: help)"
        )
        initial_error = getattr(self, "_agent_query_parse_error", None)
        self.push_screen(  # type: ignore[attr-defined]
            QueryEditModal(
                self._agent_search_query,
                title="Filter Agents",
                hint=hint,
                validator=_validator,
                initial_error=initial_error,
            ),
            on_dismiss,
        )
