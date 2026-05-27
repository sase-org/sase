"""Dismissed-agent archive loading and filtering for revival."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._revive_helpers import merge_dismissed_agents
from ._revive_index import sync_dismissed_agent_artifact_index

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentReviveArchiveMixin:
    """Mixin providing dismissed-archive loading for custom revive search."""

    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    def _show_dismissed_agents_for_scope(self, selection: object) -> None:
        """Filter dismissed agents by scope and show the selection modal."""
        from ...modals import SelectionItem
        from ...modals.revive_agent_modal import DismissedAgentSelectModal

        if not isinstance(selection, SelectionItem):
            return

        def _filter_for_scope(agents: list[Agent]) -> tuple[list[Agent], list[Agent]]:
            return self._filter_dismissed_agents_for_scope(selection, agents)

        agents = self._dismissed_agent_objects
        filtered, all_in_scope = _filter_for_scope(agents)

        def _on_agents_selected(agents: object) -> None:
            if agents is None:
                return
            if not isinstance(agents, list) or not agents:
                return
            if len(agents) == 1:
                self._do_revive_agent(  # type: ignore[attr-defined]
                    agents[0], selection_scope=selection
                )
            else:
                self._do_revive_agents(  # type: ignore[attr-defined]
                    agents, selection_scope=selection
                )

        modal = DismissedAgentSelectModal(
            filtered,
            all_dismissed=all_in_scope,
            loading_archive=True,
        )
        self.app.push_screen(modal, _on_agents_selected)  # type: ignore[attr-defined]

        async def _load_archive_for_modal() -> None:
            archive_agents = await asyncio.to_thread(self._load_dismissed_archive)
            merged = merge_dismissed_agents(
                self._dismissed_agent_objects, archive_agents
            )
            next_filtered, next_all_in_scope = _filter_for_scope(merged)
            self._dismissed_agent_objects = merged
            try:
                modal.set_agents(
                    next_filtered,
                    all_dismissed=next_all_in_scope,
                    loading_archive=False,
                )
            except Exception:
                pass

        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, _load_archive_for_modal),
                thread=False,
                exclusive=False,
                group="dismissed-archive",
            )
        except Exception:
            self.notify("Failed to load dismissed archive", severity="error")  # type: ignore[attr-defined]

    def _filter_dismissed_agents_for_scope(
        self,
        selection: object,
        agents: list[Agent],
    ) -> tuple[list[Agent], list[Agent]]:
        """Return parent options and all dismissed rows for a selected scope."""
        from ...modals import SelectionItem

        if not isinstance(selection, SelectionItem):
            return [], []
        if selection.item_type == "all":
            filtered = list(agents)
        elif selection.item_type == "home":
            filtered = [a for a in agents if a.cl_name == "~"]
        elif selection.item_type == "project":
            filtered = [
                a
                for a in agents
                if Path(a.project_file).parent.name == selection.project_name
            ]
        elif selection.item_type == "cl":
            filtered = [a for a in agents if a.cl_name == selection.cl_name]
        else:
            return [], []

        # Sort: project-level agents first, then by CL name, then most recent first
        filtered.sort(
            key=lambda a: (
                0 if a.is_project_agent else 1,
                a.cl_name,
                float("inf") if a.start_time is None else -a.start_time.timestamp(),
            )
        )

        # Only show top-level DONE entries (no child steps)
        all_in_scope = list(filtered)
        filtered = [a for a in filtered if not a.is_workflow_child]
        return filtered, all_in_scope

    def _load_dismissed_archive(self) -> list[Agent]:
        """Load dismissed bundles on demand and repair the compact identity index."""
        from ....dismissed_agents import load_dismissed_bundles, save_dismissed_agents

        archive_agents = load_dismissed_bundles()
        found_identities = {agent.identity for agent in archive_agents}
        found_suffixes = {
            agent.raw_suffix for agent in archive_agents if agent.raw_suffix is not None
        }
        in_memory_suffixes = {
            agent.raw_suffix
            for agent in self._dismissed_agent_objects
            if agent.raw_suffix is not None
        }
        next_dismissed = set(self._dismissed_agents)
        next_dismissed.update(found_identities)
        next_dismissed = {
            identity
            for identity in next_dismissed
            if identity[2] is None
            or identity[2] in found_suffixes
            or identity[2] in in_memory_suffixes
        }
        if next_dismissed != self._dismissed_agents:
            self._dismissed_agents = next_dismissed
            if save_dismissed_agents(self._dismissed_agents):
                try:
                    sync_dismissed_agent_artifact_index(
                        self._dismissed_agents, force=True
                    )
                except Exception:
                    pass
        for agent in archive_agents:
            agent._loaded_from_dismissed_bundle = True
        return archive_agents
