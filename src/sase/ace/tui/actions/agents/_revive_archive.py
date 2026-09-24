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

        dismissed_snapshot = set(self._dismissed_agents)
        dismissed_objects_snapshot = list(self._dismissed_agent_objects)
        removal_snapshot = getattr(self, "_explicit_removal_snapshot", None)
        explicit_removals = removal_snapshot() if callable(removal_snapshot) else None
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(
                    Any,
                    lambda: self._repair_dismissed_projection(
                        dismissed_snapshot=dismissed_snapshot,
                        dismissed_objects_snapshot=dismissed_objects_snapshot,
                        explicit_removals=explicit_removals,
                    ),
                ),
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

    def _repair_dismissed_projection(
        self,
        *,
        dismissed_snapshot: set[tuple[AgentType, str, str | None]] | None = None,
        dismissed_objects_snapshot: list[Agent] | None = None,
        explicit_removals: object | None = None,
    ) -> None:
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
        initial_dismissed = (
            set(self._dismissed_agents)
            if dismissed_snapshot is None
            else set(dismissed_snapshot)
        )
        initial_objects = (
            list(self._dismissed_agent_objects)
            if dismissed_objects_snapshot is None
            else list(dismissed_objects_snapshot)
        )

        def _apply() -> tuple[set[tuple[AgentType, str, str | None]], bool]:
            return self._apply_repaired_dismissed_projection(
                found_identities,
                initial_dismissed,
                initial_objects,
                explicit_removals,
            )

        # The bundle scan and save run on the worker.  Only the live-set
        # mutation returns to Textual's UI thread, so an open revive modal
        # cannot race an off-thread assignment.
        call_from_thread = getattr(self, "call_from_thread", None)
        if dismissed_snapshot is not None and callable(call_from_thread):
            next_dismissed, changed = call_from_thread(_apply)
        else:
            next_dismissed, changed = _apply()
        if changed and save_dismissed_agents(next_dismissed):
            try:
                sync_dismissed_agent_artifact_index(next_dismissed, force=True)
            except Exception:
                pass

    def _apply_repaired_dismissed_projection(
        self,
        found_identities: set[tuple[AgentType, str, str | None]],
        initial_dismissed: set[tuple[AgentType, str, str | None]],
        dismissed_objects: list[Agent],
        explicit_removals: object | None,
    ) -> tuple[set[tuple[AgentType, str, str | None]], bool]:
        """Apply one worker's repair result on the UI thread."""
        from ._removal_tombstones import EMPTY_EXPLICIT_REMOVALS

        del initial_dismissed
        found_suffixes = {
            raw_suffix
            for _, _, raw_suffix in found_identities
            if raw_suffix is not None
        }
        kill_record_suffixes = {
            agent.raw_suffix
            for agent in [*dismissed_objects, *self._dismissed_agent_objects]
            if agent.raw_suffix is not None
        }
        current = set(self._dismissed_agents)
        current_snapshot = getattr(self, "_explicit_removal_snapshot", None)
        tombstones = (
            current_snapshot()
            if callable(current_snapshot)
            else explicit_removals or EMPTY_EXPLICIT_REMOVALS
        )
        tombstone_identities = set(getattr(tombstones, "identities", ()))
        next_dismissed = {
            identity
            for identity in current | found_identities
            if identity in tombstone_identities
            or identity[2] is None
            or identity[2] in found_suffixes
            or identity[2] in kill_record_suffixes
        }
        changed = next_dismissed != current
        if changed:
            self._dismissed_agents = next_dismissed
        return next_dismissed, changed

    def _load_dismissed_archive(self) -> list[Agent]:
        """Compatibility hook for tests and older callers: repair only."""
        self._repair_dismissed_projection()
        return []
