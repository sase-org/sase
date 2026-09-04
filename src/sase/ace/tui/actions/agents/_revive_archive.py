"""Dismissed-agent archive loading and filtering for revival."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sase.ace.config import get_ace_page_size

from ...models.agent import AgentType
from ...models._timestamps import parse_timestamp_14_digit
from ._revive_helpers import merge_dismissed_agents
from ._revive_index import sync_dismissed_agent_artifact_index

if TYPE_CHECKING:
    from ...models import Agent


def _dismissed_agent_recency_key(
    agent: Agent,
) -> tuple[bool, float, str, str, str]:
    """Return a newest-first key with stable identity tie-breaking."""
    recency = agent.start_time
    if recency is None:
        recency = parse_timestamp_14_digit(agent.raw_suffix)
    return (
        recency is None,
        0.0 if recency is None else -recency.timestamp(),
        agent.agent_type.value,
        agent.cl_name,
        agent.raw_suffix or "",
    )


class AgentReviveArchiveMixin:
    """Mixin providing dismissed-archive loading for custom revive search."""

    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    def _show_dismissed_agents_for_custom_search(self) -> None:
        """Show recent dismissed agents for unscoped local filtering."""
        from ...modals.revive_agent_modal import DismissedAgentSelectModal

        visible, all_dismissed = self._dismissed_agent_rows(
            self._dismissed_agent_objects
        )
        page_size = get_ace_page_size()
        next_offset = 0
        host_snapshots: list[list[Agent]] = []

        def _load_page_for_modal() -> tuple[list[Agent], list[Agent], bool]:
            nonlocal next_offset
            from ....dismissed_agents import load_dismissed_bundles_page

            page_agents, exhausted = load_dismissed_bundles_page(
                limit=page_size,
                offset=next_offset,
            )
            next_offset += page_size
            merged = merge_dismissed_agents(
                self._dismissed_agent_objects,
                page_agents,
            )
            self._dismissed_agent_objects = merged
            host_snapshots.append(list(merged))
            next_visible, next_all_dismissed = self._dismissed_agent_rows(merged)
            return next_visible, next_all_dismissed, exhausted

        def _rewind_page_for_modal() -> None:
            nonlocal next_offset
            if len(host_snapshots) <= 1:
                return
            host_snapshots.pop()
            self._dismissed_agent_objects = list(host_snapshots[-1])
            next_offset = max(0, next_offset - page_size)

        def _on_agents_selected(agents: object) -> None:
            if agents is None:
                return
            if not isinstance(agents, list) or not agents:
                return
            if len(agents) == 1:
                self._do_revive_agent(agents[0])  # type: ignore[attr-defined]
            else:
                self._do_revive_agents(agents)  # type: ignore[attr-defined]

        modal = DismissedAgentSelectModal(
            visible,
            all_dismissed=all_dismissed,
            loading_archive=True,
            page_loader=_load_page_for_modal,
            page_rewind=_rewind_page_for_modal,
            page_size=page_size,
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

    def _dismissed_agent_rows(
        self, agents: list[Agent]
    ) -> tuple[list[Agent], list[Agent]]:
        """Return sorted visible parents and all rows for the loaded pages."""
        from ...models._agent_imported_family import (
            materialize_imported_family_containers,
        )

        agents = materialize_imported_family_containers(agents)
        all_dismissed = list(agents)
        visible = [agent for agent in agents if not agent.is_workflow_child]
        visible.sort(key=_dismissed_agent_recency_key)
        return visible, all_dismissed

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
