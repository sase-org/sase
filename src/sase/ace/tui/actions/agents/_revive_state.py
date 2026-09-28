"""Selection and in-memory state helpers for agent revival."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentReviveStateMixin:
    """Mixin providing revive selection and dismissed-state helpers."""

    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _revived_agent_raw_suffixes: set[str]

    def _select_revived_agent(self, agent: Agent) -> bool:
        """Reveal *agent* after a revive reload through the fold-expanding ladder.

        Routed through ``_try_reveal_agent_row`` so a revived row hidden
        under a fold or on another agent tab is still reachable, and a
        failed reveal restores the previous tab instead of stranding it.
        """
        complete = list(
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or ()
        )
        target_identity = agent.identity
        if not any(candidate.identity == target_identity for candidate in complete):
            # A dismissed row's identity can differ from its revived,
            # freshly-loaded counterpart; fall back to matching by suffix.
            if not agent.raw_suffix:
                return False
            match = next(
                (
                    candidate
                    for candidate in complete
                    if candidate.raw_suffix == agent.raw_suffix
                ),
                None,
            )
            if match is None:
                return False
            target_identity = match.identity

        reveal = getattr(self, "_try_reveal_agent_row", None)
        if not callable(reveal):
            return False
        return reveal(target_identity) is None

    def _remove_dismissed_aliases_for_suffixes(self, suffixes: set[str]) -> None:
        """Remove dismissed identities whose raw_suffix matches revived suffixes.

        Loader suppression uses suffix-based matching in addition to exact
        identity checks. Revive must clear all aliases sharing revived suffixes
        so restored artifacts can reappear in the panel.
        """
        if not suffixes:
            return
        self._dismissed_agents = {
            identity
            for identity in self._dismissed_agents
            if identity[2] is None or identity[2] not in suffixes
        }

    def _persist_revived_dismissals(
        self,
        identities: set[tuple[AgentType, str, str | None]],
        suffixes: set[str],
    ) -> set[tuple[AgentType, str, str | None]] | None:
        """Remove revived identities from the on-disk dismissed index.

        Removes *identities* plus any other on-disk alias that shares a
        revived suffix, merging under the index lock so dismissals other
        writers added meanwhile survive. Returns the resulting on-disk set,
        or None when the index could not be written.
        """
        from ....dismissed_agents import remove_dismissed_agents

        try:
            remaining = remove_dismissed_agents(identities)
            aliases = {
                identity
                for identity in remaining
                if identity[2] is not None and identity[2] in suffixes
            }
            if aliases:
                remaining = remove_dismissed_agents(aliases)
        except OSError:
            return None
        return remaining

    def _record_revived_agent_suffixes(self, suffixes: set[str]) -> None:
        """Remember revived suffixes across incomplete Tier 1 refreshes."""
        if not suffixes:
            return
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if revived_suffixes is None:
            revived_suffixes = set()
            self._revived_agent_raw_suffixes = revived_suffixes
        revived_suffixes.update(suffixes)
