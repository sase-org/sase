"""Immutable rendering records for derived plan associations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanAgentAssociation:
    """One agent entry ready for the plan-header renderer."""

    label: str
    target: str | None
    sort_key: str
    trailing_text: str | None = None


@dataclass(frozen=True, slots=True)
class PlanCommitAssociation:
    """One commit entry ready for the plan-header renderer."""

    label: str
    target: str | None
    trailing_text: str
    sort_key: tuple[int, str]
    sha: str


@dataclass(frozen=True, slots=True)
class PlanAssociations:
    """The derived ``AGENTS`` and ``COMMITS`` sections for one plan."""

    agents: tuple[PlanAgentAssociation, ...] = ()
    commits: tuple[PlanCommitAssociation, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanAssociationIndex:
    """Reusable association projection for every plan in one store."""

    by_plan: Mapping[str, PlanAssociations]
    diagnostics: tuple[str, ...] = ()

    def for_plan(self, plan_ref: str) -> PlanAssociations:
        """Return associations for a canonical reference, or empty sections."""

        return self.by_plan.get(plan_ref, PlanAssociations())


__all__ = [
    "PlanAgentAssociation",
    "PlanAssociationIndex",
    "PlanAssociations",
    "PlanCommitAssociation",
]
