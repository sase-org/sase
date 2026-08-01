"""Value types shared by associated-plan resolution modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.bead.model import TaskPlusOneEvidence
from sase.bead_type_presentation import BeadTypeValue
from sase.phase_size_presentation import PhaseSizeValue
from sase.sdd.plan_display import (
    AuthoredPlanTier as AuthoredPlanTier,
    PlanDisplay as AssociatedPlanSummary,
    PlanDisplayPhase as AssociatedPlanPhaseSummary,
    PlanDisplayTier as AssociatedPlanTier,
    PlanFileMetadata as PlanFileMetadata,
    PlanPhaseAvailability as AssociatedPlanPhaseAvailability,
)

AgentPlanRole = Literal["ordinary", "author", "phase", "task", "land"]
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
class BeadSummary:
    """Immutable type-aware bead metadata consumed by the BEAD lane."""

    id: str
    phase_title: str | None
    description: str | None
    actual_plan_path: str | None
    display_plan_path: str | None
    plan_exists: bool
    plan_readable: bool
    epic_title: str | None
    size: PhaseSizeValue | None
    bead_type: BeadTypeValue = "phase"
    notes: str | None = None
    plus_one_evidence: tuple[TaskPlusOneEvidence, ...] = ()

    @property
    def plus_one_count(self) -> int:
        """Return the derived corroboration count for task summaries."""

        return len(self.plus_one_evidence)

    @property
    def title(self) -> str | None:
        """Return the type-neutral title for the selected bead."""
        return self.phase_title


# Compatibility name retained for existing integrations and phase-focused tests.
PhaseBeadSummary = BeadSummary


@dataclass(frozen=True, slots=True)
class AgentPlanEnrichment:
    """Independent BEAD and PLAN relationships for deferred enrichment.

    A phase row may carry both summaries: BEAD is anchored to its parent epic,
    while PLAN describes the plan authored by that phase agent. Every consumed
    path is retained so generic artifact discovery cannot duplicate either
    relationship.
    """

    role: AgentPlanRole
    phase_bead: BeadSummary | None
    associated_plan: AssociatedPlanSummary | None
    resolved_plan_paths: tuple[str, ...]

    @property
    def resolved_plan_path(self) -> str | None:
        """Compatibility alias for callers that only handled one plan path."""
        return self.resolved_plan_paths[0] if self.resolved_plan_paths else None

    @property
    def bead_summary(self) -> BeadSummary | None:
        """Return the generalized bead summary."""
        return self.phase_bead


@dataclass(frozen=True, slots=True)
class PlanFileCacheEntry:
    signature: PlanFileSignature | None
    metadata: PlanFileMetadata
    expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPlanAssociation:
    path: Path | None
    known_epic: bool = False
    role: Literal["phase", "task", "land"] | None = None
    plan_reference: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None
    bead_summary: BeadSummary | None = None
    notes: str | None = None


def normalize_bead_notes(text: str | None) -> str | None:
    """Normalize persisted bead notes without flattening intentional lines."""
    if not text:
        return None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalized or None
