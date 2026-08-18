"""One-shot Agents-tab search-query seed from the current project.

Resolve happens on the same worker that already loads agent data. The
seeded ``project:`` term is the same ``_agent_search_query`` string that
the list finalize pipeline, unread-jump candidate cache, and
prospective-clan projection already consume — there is no second filter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.current_project import CurrentProject


class AgentSearchQuerySeedMixin:
    """Seed ``_agent_search_query`` once from the resolved current project."""

    _agent_search_query: str
    _agent_search_query_seeded: bool
    _agent_search_query_seed_attempted: bool

    def _should_seed_agent_search_query(self) -> bool:
        """Return whether this session still needs a current-project seed."""
        if getattr(self, "_agent_search_query_seed_attempted", False):
            return False
        settings = getattr(self, "_current_project_settings", None)
        if settings is None or not getattr(settings, "seed_agents_query", False):
            return False
        return not (getattr(self, "_agent_search_query", "") or "").strip()

    def _maybe_seed_agent_search_query(self, current: CurrentProject | None) -> bool:
        """Seed the Agents-tab query once. Return True if the query changed.

        Never overrides a query the user already typed. An empty resolve still
        counts as the session's one seed attempt so a later MRU write cannot
        retroactively re-scope an already-open Agents tab.
        """
        if getattr(self, "_agent_search_query_seed_attempted", False):
            return False
        self._agent_search_query_seed_attempted = True
        settings = getattr(self, "_current_project_settings", None)
        if settings is None or not getattr(settings, "seed_agents_query", False):
            return False
        if (getattr(self, "_agent_search_query", "") or "").strip():
            return False
        display_name = (getattr(current, "display_name", None) or "").strip()
        if not display_name:
            return False
        from sase.ace.agent_query import project_query_term

        self._agent_search_query = project_query_term(display_name)
        self._agent_search_query_seeded = True
        return True
