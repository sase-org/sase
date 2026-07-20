"""Value types shared by associated-plan resolution modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.phase_size_presentation import PhaseSizeValue

AssociatedPlanTier = Literal["plan", "tale", "epic"]
AuthoredPlanTier = Literal["tale", "epic"]
AgentPlanRole = Literal["ordinary", "author", "phase", "land"]
_InitialAgentPlanRole = Literal[
    "ordinary",
    "author",
    "phase",
    "land",
    "ambiguous",
]
AssociatedPlanPhaseAvailability = Literal[
    "not-applicable",
    "available",
    "unavailable",
]
PlanAssociationCacheKey = tuple[str, str, str | None, str | None, int]
PlanFileSignature = tuple[int, int]


@dataclass(frozen=True, slots=True)
class AssociatedPlanPhaseSummary:
    """Immutable normalized epic phase consumed by the render path."""

    id: str
    title: str
    depends_on: tuple[str, ...]
    description: str | None
    size: PhaseSizeValue
    model: str | None


@dataclass(frozen=True, slots=True)
class AssociatedPlanSummary:
    """Immutable plan metadata consumed by the in-memory render path."""

    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    effective_tier: AssociatedPlanTier | None
    actual_path: str
    display_path: str
    committed: bool | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: AssociatedPlanPhaseAvailability
    phases: tuple[AssociatedPlanPhaseSummary, ...]


@dataclass(frozen=True, slots=True)
class PhaseBeadSummary:
    """Immutable selected-phase metadata consumed by the BEAD lane."""

    id: str
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
class PlanFileMetadata:
    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: AssociatedPlanPhaseAvailability
    phases: tuple[AssociatedPlanPhaseSummary, ...]


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
