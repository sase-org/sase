"""Session-local tombstones for rows explicitly removed from the Agents tab."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


AgentIdentity = tuple["AgentType", str, str | None]


@dataclass(frozen=True)
class ExplicitRemovalSnapshot:
    """An immutable, O(1)-lookup view of this TUI session's removals."""

    identities: frozenset[AgentIdentity]
    suffixes: frozenset[str]
    cl_suffixes: frozenset[tuple[str, str]]

    @classmethod
    def from_identities(
        cls, identities: Iterable[AgentIdentity]
    ) -> ExplicitRemovalSnapshot:
        values = frozenset(identities)
        return cls(
            identities=values,
            suffixes=frozenset(
                raw_suffix for _, _, raw_suffix in values if raw_suffix is not None
            ),
            cl_suffixes=frozenset(
                (cl_name, raw_suffix)
                for _, cl_name, raw_suffix in values
                if raw_suffix is not None
            ),
        )


EMPTY_EXPLICIT_REMOVALS = ExplicitRemovalSnapshot(
    identities=frozenset(), suffixes=frozenset(), cl_suffixes=frozenset()
)


def is_explicitly_removed(agent: Agent, snapshot: ExplicitRemovalSnapshot) -> bool:
    """Return whether *agent* is covered by a session removal tombstone.

    A reload may label a killed workflow as a RUNNING row before dedup.  The
    suffix-plus-clan match deliberately catches that representation change;
    ``unknown`` remains the existing transient fallback.
    """
    if agent.identity in snapshot.identities:
        return True
    raw_suffix = agent.raw_suffix
    if raw_suffix is None:
        return False
    return (agent.cl_name, raw_suffix) in snapshot.cl_suffixes or (
        agent.cl_name == "unknown" and raw_suffix in snapshot.suffixes
    )


def filter_explicitly_removed(
    agents: Iterable[Agent], snapshot: ExplicitRemovalSnapshot
) -> list[Agent]:
    """Filter removed rows and rebuild derived clan containers."""
    from ...models._agent_tree import project_clan_tree

    return project_clan_tree(
        [agent for agent in agents if not is_explicitly_removed(agent, snapshot)]
    )


class AgentRemovalTombstonesMixin:
    """Own the session-only removal state shared by every roster publisher."""

    _explicit_removals: set[AgentIdentity]
    _explicit_removal_suffixes: set[str]
    _explicit_removal_cl_suffixes: set[tuple[str, str]]
    _agents_removal_generation: int

    def _explicit_removal_snapshot(self) -> ExplicitRemovalSnapshot:
        identities = frozenset(getattr(self, "_explicit_removals", ()))
        return ExplicitRemovalSnapshot(
            identities=identities,
            suffixes=frozenset(getattr(self, "_explicit_removal_suffixes", ())),
            cl_suffixes=frozenset(getattr(self, "_explicit_removal_cl_suffixes", ())),
        )

    def record_explicit_removals(self, identities: Iterable[AgentIdentity]) -> None:
        """Record user-driven removals synchronously on the UI thread."""
        additions = set(identities) - getattr(self, "_explicit_removals", set())
        if not additions:
            return
        explicit = getattr(self, "_explicit_removals", None)
        if explicit is None:
            explicit = set()
            self._explicit_removals = explicit
        explicit.update(additions)
        suffixes = getattr(self, "_explicit_removal_suffixes", None)
        if suffixes is None:
            suffixes = set()
            self._explicit_removal_suffixes = suffixes
        cl_suffixes = getattr(self, "_explicit_removal_cl_suffixes", None)
        if cl_suffixes is None:
            cl_suffixes = set()
            self._explicit_removal_cl_suffixes = cl_suffixes
        for _, cl_name, raw_suffix in additions:
            if raw_suffix is not None:
                suffixes.add(raw_suffix)
                cl_suffixes.add((cl_name, raw_suffix))
        self._agents_removal_generation = (
            int(getattr(self, "_agents_removal_generation", 0)) + 1
        )

    def clear_explicit_removals(self, identities: Iterable[AgentIdentity]) -> None:
        """Remove revive targets from the session tombstone set."""
        removals = set(identities)
        explicit = set(getattr(self, "_explicit_removals", ()))
        retained = explicit - removals
        if retained == explicit:
            return
        rebuilt = ExplicitRemovalSnapshot.from_identities(retained)
        self._explicit_removals = set(rebuilt.identities)
        self._explicit_removal_suffixes = set(rebuilt.suffixes)
        self._explicit_removal_cl_suffixes = set(rebuilt.cl_suffixes)
        self._agents_removal_generation = (
            int(getattr(self, "_agents_removal_generation", 0)) + 1
        )

    def is_explicitly_removed(
        self, agent: Agent, snapshot: ExplicitRemovalSnapshot | None = None
    ) -> bool:
        return is_explicitly_removed(
            agent,
            self._explicit_removal_snapshot() if snapshot is None else snapshot,
        )

    def filter_explicitly_removed(
        self,
        agents: Iterable[Agent],
        snapshot: ExplicitRemovalSnapshot | None = None,
    ) -> list[Agent]:
        return filter_explicitly_removed(
            agents,
            self._explicit_removal_snapshot() if snapshot is None else snapshot,
        )


__all__ = [
    "AgentIdentity",
    "AgentRemovalTombstonesMixin",
    "EMPTY_EXPLICIT_REMOVALS",
    "ExplicitRemovalSnapshot",
    "filter_explicitly_removed",
    "is_explicitly_removed",
]
