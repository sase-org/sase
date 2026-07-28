"""Immutable rendering records for derived bead associations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BeadAgentAssociation:
    """One agent entry ready for bead-page rendering."""

    label: str
    target: str | None
    bead_id: str
    commit_count: int
    sort_key: tuple[str, str]


@dataclass(frozen=True, slots=True)
class BeadCommitAssociation:
    """One commit entry ready for bead-page rendering."""

    label: str
    target: str | None
    bead_id: str
    subject: str
    committed_at: int
    sort_key: tuple[int, str]
    sha: str


@dataclass(frozen=True, slots=True)
class BeadAssociations:
    """The derived agent and commit sections for one bead."""

    agents: tuple[BeadAgentAssociation, ...] = ()
    commits: tuple[BeadCommitAssociation, ...] = ()


@dataclass(frozen=True, slots=True)
class BeadAssociationIndex:
    """Reusable association projection for every bead in one store."""

    by_bead: Mapping[str, BeadAssociations]
    diagnostics: tuple[str, ...] = ()

    def for_bead(self, bead_id: str) -> BeadAssociations:
        """Return associations for *bead_id*, or empty sections."""

        return self.by_bead.get(bead_id, BeadAssociations())


__all__ = [
    "BeadAgentAssociation",
    "BeadAssociationIndex",
    "BeadAssociations",
    "BeadCommitAssociation",
]
