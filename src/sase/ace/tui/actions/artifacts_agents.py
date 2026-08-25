"""App-level actions for the Artifacts Agent pane.

Selection/entry navigation, marks, and relation/grouping actions all reach
this pane already through the generic ``_artifacts_entry_navigator()``
resolver (see ``artifacts_navigation.py``); this mixin supplies only the
by-id lookup the clipboard actions need, mirroring ``_files_pane()`` /
``_beads_pane()``. It also owns Agent-pane-specific actions.
"""

from __future__ import annotations

from collections.abc import Iterable

from sase.ace.tui.models import Agent
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.agents_revival import AgentsRevivalRequest
from sase.agents.catalog import AgentCatalogRow

from ..tab_order import ARTIFACTS_TAB

AGENTS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {"agents_next", "agents_prev", "agents_revive"}
)


class ArtifactsAgentsActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Agent pane."""

    def _agents_pane(self) -> ArtifactsAgentsPane | None:
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#artifacts-agents-pane",
                ArtifactsAgentsPane,
            )
        except Exception:
            return None

    def action_agents_next(self) -> None:
        pane = self._agents_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
        try:
            pane.move_selection(1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_agents_prev(self) -> None:
        pane = self._agents_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
        try:
            pane.move_selection(-1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_agents_revive(self) -> None:
        """Revive the selected or marked Artifacts Agent pane row(s)."""

        if (
            getattr(self, "current_tab", None) != ARTIFACTS_TAB
            or getattr(self, "current_artifacts_pane_key", None) != "agents"
        ):
            return
        pane = self._agents_pane()
        if pane is None:
            return

        marks = getattr(self, "_artifacts_marked_targets", {}).get("agents", set())
        request = pane.revive_request(marks)
        if request.seed_query is not None:
            pane.apply_seed_query(request.seed_query)
            if request.message:
                self.notify(  # type: ignore[attr-defined]
                    request.message,
                    severity=request.severity,
                )
            return
        if request.message:
            self.notify(  # type: ignore[attr-defined]
                request.message,
                severity=request.severity,
            )
            return
        if not request.rows:
            return

        agents = self._load_revivable_catalog_agents(request.rows)
        if not agents:
            self.notify(  # type: ignore[attr-defined]
                "Could not load dismissed bundle(s) for selected agent(s)",
                severity="warning",
            )
            return

        if len(agents) == 1:
            delta = self._do_revive_agent(agents[0])  # type: ignore[attr-defined]
        else:
            delta = self._do_revive_agents(agents)  # type: ignore[attr-defined]
        if delta is False:
            return
        pane.consume_revive_delta(delta, preferred_target=request.preferred_target)
        self._clear_artifacts_marks_for_pane("agents")  # type: ignore[attr-defined]
        if request.skipped_count:
            self.notify(  # type: ignore[attr-defined]
                f"Skipped {request.skipped_count} marked non-revivable agent(s)",
                severity="warning",
            )

    def _load_revivable_catalog_agents(
        self,
        rows: Iterable[AgentCatalogRow],
    ) -> list[Agent]:
        """Load real dismissed Agent objects for catalog rows selected to revive."""

        selected_rows = tuple(rows)
        suffixes = {row.raw_suffix for row in selected_rows if row.raw_suffix}
        if not suffixes:
            return []

        from sase.ace.dismissed_agents import (
            load_dismissed_bundle_summaries,
            load_dismissed_bundles,
        )
        from .agents._revive_helpers import merge_dismissed_agents

        parent_suffixes = set(suffixes)
        for summary in load_dismissed_bundle_summaries():
            if (
                summary.parent_timestamp in parent_suffixes
                or summary.retry_of_timestamp in parent_suffixes
            ):
                suffixes.add(summary.raw_suffix)

        loaded = load_dismissed_bundles(suffixes)
        dismissed_objects = getattr(self, "_dismissed_agent_objects", [])
        self._dismissed_agent_objects = merge_dismissed_agents(  # type: ignore[attr-defined]
            dismissed_objects,
            loaded,
        )

        loaded_by_path = {
            str(path): agent
            for agent in loaded
            if (path := getattr(agent, "_dismissed_bundle_path", None))
        }
        loaded_by_suffix = {
            agent.raw_suffix: agent for agent in loaded if agent.raw_suffix is not None
        }

        agents: list[Agent] = []
        for row in selected_rows:
            agent = _agent_for_row(
                row,
                loaded_by_path=loaded_by_path,
                loaded_by_suffix=loaded_by_suffix,
            )
            if agent is not None:
                agents.append(agent)
        return agents


def _agent_for_row(
    row: AgentCatalogRow,
    *,
    loaded_by_path: dict[str, Agent],
    loaded_by_suffix: dict[str, Agent],
) -> Agent | None:
    if row.bundle_path:
        agent = loaded_by_path.get(row.bundle_path)
        if agent is not None:
            return agent
    if row.raw_suffix:
        return loaded_by_suffix.get(row.raw_suffix)
    return None


__all__ = [
    "AGENTS_ARTIFACT_ACTIONS",
    "ArtifactsAgentsActionsMixin",
    "AgentsRevivalRequest",
    "_agent_for_row",
]
