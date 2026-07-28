"""Value types shared by associated-plan resolution modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.phase_size_presentation import PhaseSizeValue
from sase.sdd.plan_display import (
    AuthoredPlanTier as AuthoredPlanTier,
    PlanDisplay as AssociatedPlanSummary,
    PlanDisplayPhase as AssociatedPlanPhaseSummary,
    PlanDisplayTier as AssociatedPlanTier,
    PlanFileMetadata as PlanFileMetadata,
    PlanPhaseAvailability as AssociatedPlanPhaseAvailability,
)

AgentPlanRole = Literal["ordinary", "author", "phase", "land"]
_InitialAgentPlanRole = Literal[
    "ordinary",
    "author",
    "phase",
    "land",
    "ambiguous",
]
PlanAssociationCacheKey = tuple[str, str, str | None, str | None, int]
PlanFileSignature = tuple[int, int]


@dataclass(frozen=True, slots=True)
class PhaseBeadSummary:
    """Immutable selected-phase metadata consumed by the BEAD lane."""

    id: str
    phase_title: str | None
    description: str | None
    actual_plan_path: str | None
    display_plan_path: str | None
    plan_exists: bool
    plan_readable: bool
    epic_title: str | None
    size: PhaseSizeValue | None


@dataclass(frozen=True, slots=True)
class AgentPlanEnrichment:
    """Independent BEAD and PLAN relationships for deferred enrichment.

    A phase row may carry both summaries: BEAD is anchored to its parent epic,
    while PLAN describes the plan authored by that phase agent. Every consumed
    path is retained so generic artifact discovery cannot duplicate either
    relationship.
    """

    role: AgentPlanRole
    phase_bead: PhaseBeadSummary | None
    associated_plan: AssociatedPlanSummary | None
    resolved_plan_paths: tuple[str, ...]

    @property
    def resolved_plan_path(self) -> str | None:
        """Compatibility alias for callers that only handled one plan path."""
        return self.resolved_plan_paths[0] if self.resolved_plan_paths else None


@dataclass(frozen=True, slots=True)
class PlanFileCacheEntry:
    signature: PlanFileSignature | None
    metadata: PlanFileMetadata
    expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPlanAssociation:
    path: Path | None
    known_epic: bool = False
    role: Literal["phase", "land"] | None = None
    plan_reference: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None
