"""Dismissed-agent archive loading and filtering for revival."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ...models.agent import AgentType
from ._revive_index import sync_dismissed_agent_artifact_index

if TYPE_CHECKING:
    from ...models import Agent


class AgentReviveArchiveMixin:
    """Mixin that repairs the dismissed-agent identity projection."""

    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

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
            update_dismissed_agents,
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

        def _apply() -> tuple[
            set[tuple[AgentType, str, str | None]],
            set[tuple[AgentType, str, str | None]],
        ]:
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
            added, removed = call_from_thread(_apply)
        else:
            added, removed = _apply()
        if not added and not removed:
            return
        # Merge only this repair's delta so dismissals other writers added
        # meanwhile survive.
        try:
            persisted = update_dismissed_agents(added, removed)
        except OSError:
            return
        try:
            sync_dismissed_agent_artifact_index(persisted, force=True)
        except Exception:
            pass

    def _apply_repaired_dismissed_projection(
        self,
        found_identities: set[tuple[AgentType, str, str | None]],
        initial_dismissed: set[tuple[AgentType, str, str | None]],
        dismissed_objects: list[Agent],
        explicit_removals: object | None,
    ) -> tuple[
        set[tuple[AgentType, str, str | None]],
        set[tuple[AgentType, str, str | None]],
    ]:
        """Apply one worker's repair result on the UI thread.

        Returns the identities the repair added to and removed from the live
        dismissed set, for the caller to merge into the on-disk index.
        """
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
        added = next_dismissed - current
        removed = current - next_dismissed
        if added or removed:
            self._dismissed_agents = next_dismissed
        return added, removed

    def _load_dismissed_archive(self) -> list[Agent]:
        """Compatibility hook for tests and older callers: repair only."""
        self._repair_dismissed_projection()
        return []
