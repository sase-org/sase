"""Immutable values shared by plan-display loading and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.phase_size_presentation import PhaseSizeValue
from sase.sdd.plan_header_block import PlanHeaderSectionKind

PlanDisplayTier = Literal["plan", "tale", "epic"]
AuthoredPlanTier = Literal["tale", "epic"]
PlanPhaseAvailability = Literal[
    "not-applicable",
    "available",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class PlanDisplayPhase:
    """One normalized epic phase ready for presentation."""

    id: str
    title: str
    depends_on: tuple[str, ...]
    description: str | None
    size: PhaseSizeValue
    model: str | None


@dataclass(frozen=True, slots=True)
class PlanProvenanceSection:
    """One plan-header block section reduced to display labels."""

    kind: PlanHeaderSectionKind
    entries: tuple[str, ...]
    omitted: int = 0


@dataclass(frozen=True, slots=True)
class PlanFileMetadata:
    """Best-effort authored metadata plus strict validation state."""

    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: PlanPhaseAvailability
    phases: tuple[PlanDisplayPhase, ...]
    validation_ok: bool = False
    validation_diagnostics: tuple[str, ...] = ()
    provenance: tuple[PlanProvenanceSection, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanDisplay:
    """Display-shaped plan metadata shared by TUI and script consumers."""

    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    effective_tier: PlanDisplayTier | None
    actual_path: str
    display_path: str
    committed: bool | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: PlanPhaseAvailability
    phases: tuple[PlanDisplayPhase, ...]
    validation_ok: bool = False
    validation_diagnostics: tuple[str, ...] = ()
    provenance: tuple[PlanProvenanceSection, ...] = ()


__all__ = [
    "AuthoredPlanTier",
    "PlanDisplay",
    "PlanDisplayPhase",
    "PlanDisplayTier",
    "PlanFileMetadata",
    "PlanPhaseAvailability",
]
