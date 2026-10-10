"""Filter actions for the Agents tab."""

from __future__ import annotations

from collections.abc import Callable


class AgentFilterActionsMixin:
    """Mixin providing agent visibility and query filter actions."""

    current_tab: str
    hide_non_run_agents: bool
    _agent_search_query: str
    _agent_search_query_seeded: bool

    def action_toggle_hide_non_run_agents(self) -> None:
        """Toggle visibility of non-run agents (Agents tab only)."""
        if self.current_tab != "agents":
            return
        self._toggle_hide_non_run_agents()

    def action_agents_filters(self) -> None:
        """Open the auto-hiding Agents-tab filter bar directly (bound to ``f``)."""
        self.show_agents_filters()  # type: ignore[attr-defined]

    def _toggle_hide_non_run_agents(self) -> None:
        """Toggle visibility of non-run agents and refresh the display."""
        self.hide_non_run_agents = not self.hide_non_run_agents
        self._refilter_agents()  # type: ignore[attr-defined]
        # The hide filter is applied by the disk-load pipeline, not by the
        # in-memory refilter: the cached ``_agents_with_children`` list was
        # built with the previous flag value, so a reload is required for
        # the toggle to take effect.
        self._schedule_agents_async_refresh(source="filter")  # type: ignore[attr-defined]

    def _show_hidden_agents_for_navigation(
        self, on_complete: Callable[[], None]
    ) -> None:
        """Turn ``I`` off and resume a Node Finder jump after the reload."""
        self.hide_non_run_agents = False
        self._refilter_agents()  # type: ignore[attr-defined]
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source="filter", on_complete=on_complete
        )

    def _edit_agent_search_query(self) -> None:
        """Edit the agent search/filter query via the auto-hiding filter bar."""
        self.show_agents_filters()  # type: ignore[attr-defined]
