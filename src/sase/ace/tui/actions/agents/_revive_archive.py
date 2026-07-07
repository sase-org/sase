"""Dismissed-agent archive loading and filtering for revival."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ...models.agent import AgentType
from ._revive_helpers import merge_dismissed_agents
from ._revive_index import sync_dismissed_agent_artifact_index

if TYPE_CHECKING:
    from ...models import Agent


class AgentReviveArchiveMixin:
    """Mixin providing dismissed-archive loading for custom revive search."""

    _DISMISSED_ARCHIVE_PAGE_SIZE = 250

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

        scope_args = self._dismissed_archive_scope_args(selection)
        agents = self._dismissed_agent_objects
        filtered, all_in_scope = _filter_for_scope(agents)
        next_offset = 0

        def _load_page_for_modal() -> tuple[list[Agent], list[Agent], bool]:
            nonlocal next_offset
            from ....dismissed_agents import load_dismissed_bundles_page

            page_agents, exhausted = load_dismissed_bundles_page(
                **scope_args,
                limit=self._DISMISSED_ARCHIVE_PAGE_SIZE,
                offset=next_offset,
            )
            next_offset += self._DISMISSED_ARCHIVE_PAGE_SIZE
            merged = merge_dismissed_agents(
                self._dismissed_agent_objects,
                page_agents,
            )
            self._dismissed_agent_objects = merged
            next_filtered, next_all_in_scope = _filter_for_scope(merged)
            return next_filtered, next_all_in_scope, exhausted

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
            page_loader=_load_page_for_modal,
            page_size=self._DISMISSED_ARCHIVE_PAGE_SIZE,
        )
        self.app.push_screen(modal, _on_agents_selected)  # type: ignore[attr-defined]

        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._repair_dismissed_projection),
                thread=True,
                exclusive=False,
                group="dismissed-projection-repair",
            )
        except Exception:
            self.notify("Failed to repair dismissed projection", severity="error")  # type: ignore[attr-defined]

    def _dismissed_archive_scope_args(self, selection: object) -> dict[str, str]:
        """Return dismissed-bundle index query args for a revive scope."""
        from ...modals import SelectionItem

        if not isinstance(selection, SelectionItem):
            return {}
        if selection.item_type == "home":
            return {"cl_name": "~"}
        if selection.item_type == "project" and selection.project_name:
            return {"project_name": selection.project_name}
        if selection.item_type == "cl" and selection.cl_name:
            return {"cl_name": selection.cl_name}
        return {}

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

        # Sort: project-level agents first, then by ChangeSpec name, then most recent first
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

    def _repair_dismissed_projection(self) -> None:
        """Repair the compact dismissed identity projection from bundle identities."""
        from ....dismissed_agents import (
            load_dismissed_bundle_identities,
            save_dismissed_agents,
        )

        found_identities: set[tuple[AgentType, str, str | None]] = set()
        for agent_type, cl_name, raw_suffix in load_dismissed_bundle_identities():
            try:
                normalized_type = AgentType(agent_type)
            except ValueError:
                continue
            found_identities.add((normalized_type, cl_name, raw_suffix))
        found_suffixes = {
            raw_suffix
            for _, _, raw_suffix in found_identities
            if raw_suffix is not None
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

    def _load_dismissed_archive(self) -> list[Agent]:
        """Compatibility hook for tests and older callers: repair only."""
        self._repair_dismissed_projection()
        return []
