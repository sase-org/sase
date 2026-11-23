"""In-place row patching for bead warmup results.

This module owns the UI-thread apply leg: matching worker results back to the
current agent objects by identity and patching only the rows whose confirmed
state changed. Candidate construction lives in
:mod:`._loading_bead_warmup_candidates` and scheduling in
:mod:`._loading_bead_warmup_scan`; both are reached through ``self``.
"""

from __future__ import annotations

import logging

from ...agent_completion import (
    agent_wait_status_maps_for_app,
    wait_dependency_status_counts,
)
from ...models.agent_stranded import stranded_project_key_for_agent
from ...models.agent_wait_beads import cached_wait_bead_status_snapshot
from ._loading_bead_warmup_types import AgentBeadWarmupResults
from ._loading_state import AgentLoadingStateMixin

log = logging.getLogger(__name__)

__all__ = [
    "AgentBeadWarmupApplyMixin",
]


class AgentBeadWarmupApplyMixin(AgentLoadingStateMixin):
    """Patch rows whose confirmed bead state changed on the UI thread."""

    def _apply_bead_warmup_results(
        self,
        results: AgentBeadWarmupResults,
    ) -> None:
        """Patch rows whose confirmed bead state changed on the UI thread.

        Matches results back to the *current* agent objects by identity (the
        list may have been rebuilt since the worker snapshot). Only rows whose
        confirmed state changed appear in *results*, so this patches exactly the
        rows that gained or lost the bead glyph; the confirmed string itself
        lives in the bead cache that row rendering reads. ``_try_patch_agent_row``
        is a no-op off the Agents tab, where the warmed cache simply feeds the
        next render.
        """
        if not results:
            return
        blocked_for = self._warmup_activity_blocked_for()  # type: ignore[attr-defined]
        if blocked_for is not None:
            self.set_timer(  # type: ignore[attr-defined]
                blocked_for,
                lambda: self._apply_bead_warmup_results(results),
            )
            return
        if getattr(self, "current_tab", "agents") != "agents":
            return

        from ._roster_generation import get_roster_generation

        generation = get_roster_generation(self)
        if getattr(self, "_bead_warmup_index_generation", None) != generation:
            self._refresh_bead_warmup_indexes(generation)  # type: ignore[attr-defined]
        current_by_identity = getattr(self, "_bead_warmup_agent_by_identity", {})
        surfaced_agents = self._surfaced_bead_warmup_agents()  # type: ignore[attr-defined]
        surfaced_by_identity = {
            agent.identity: current_by_identity.get(agent.identity, agent)
            for agent in surfaced_agents
        }

        wait_status_maps = None
        needs_rebuild = False
        changed_identities = {
            *results.bead_display_results,
            *results.wait_bead_status_identities,
            *results.follow_progress_identities,
        }
        if results.stranded_warmed_projects:
            try:
                from ._stranded_toasts import announce_stranded_transitions

                announce_stranded_transitions(
                    self.notify,  # type: ignore[attr-defined]
                    results.stranded_warmed_projects,
                )
            except Exception:
                log.debug("stranded toast compare failed", exc_info=True)
        if results.stranded_changed_projects:
            from ...models._agent_clan import clan_members

            for identity, candidate in surfaced_by_identity.items():
                project_keys = {
                    stranded_project_key_for_agent(candidate),
                }
                if candidate.is_clan_container:
                    project_keys.update(
                        stranded_project_key_for_agent(member)
                        for member in clan_members(candidate)
                    )
                project_keys.discard(None)
                if project_keys & results.stranded_changed_projects:
                    changed_identities.add(identity)
        if results.wait_bead_status_identities:
            from ...models._agent_clan import clan_members

            for identity, candidate in surfaced_by_identity.items():
                if not candidate.is_clan_container:
                    continue
                if any(
                    member.identity in results.wait_bead_status_identities
                    for member in clan_members(candidate)
                ):
                    changed_identities.add(identity)

        for identity, target in surfaced_by_identity.items():
            if identity not in changed_identities:
                continue
            wait_counts = None
            if identity in results.wait_bead_status_identities:
                if wait_status_maps is None:
                    wait_status_maps = agent_wait_status_maps_for_app(self)
                    if wait_status_maps is None:
                        from ...agent_completion import collect_agent_wait_status_maps

                        wait_status_maps = collect_agent_wait_status_maps(
                            self._agents_with_children or self._agents
                        )
                wait_counts = wait_dependency_status_counts(
                    target,
                    wait_status_maps,
                    cached_wait_bead_status_snapshot(target),
                )
            patched = self._try_patch_agent_row(  # type: ignore[attr-defined]
                target,
                wait_dependency_counts=wait_counts,
            )
            if not patched:
                needs_rebuild = True

        if results.stranded_changed_projects:
            update_info = getattr(self, "_update_agents_info_panel", None)
            if callable(update_info) and getattr(self, "current_tab", None) == "agents":
                update_info()

        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)
