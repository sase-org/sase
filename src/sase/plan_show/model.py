"""Versioned, I/O-free model for ``sase plan show``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


SHOW_SCHEMA_VERSION = 1

PlanShowTargetKind = Literal["path", "ref", "proposal", "name", "bead"]
PlanShowTargetStatus = Literal["exact", "drifted"]
PlanShowSource = Literal["repo", "local", "file"]


@dataclass(frozen=True, slots=True)
class PlanShowTarget:
    """Which rung matched *raw* and what it resolved against."""

    raw: str | None
    kind: PlanShowTargetKind
    status: PlanShowTargetStatus
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanShowValidation:
    """Launch-mode validation state for the resolved plan."""

    ok: bool
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanShowProvenanceSection:
    """One plan-header provenance section reduced to display-ready values."""

    kind: str
    entries: tuple[str, ...]
    targets: tuple[str | None, ...] = ()
    omitted: int = 0


@dataclass(frozen=True, slots=True)
class PlanShowPhase:
    """One normalized epic phase."""

    id: str
    title: str
    depends_on: tuple[str, ...]
    size: str
    model: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class PlanShowPlan:
    """The resolved plan file's presentation-ready content."""

    reference: str | None
    path: str
    relpath: str
    source: PlanShowSource
    exists: bool
    tier: str | None
    status: str | None
    title: str | None
    goal: str | None
    created_at: str | None
    frontmatter: dict[str, Any]
    body: str
    validation: PlanShowValidation
    provenance: tuple[PlanShowProvenanceSection, ...] = ()
    phases: tuple[PlanShowPhase, ...] = ()
    waves: tuple[tuple[str, ...], ...] | None = None


@dataclass(frozen=True, slots=True)
class PlanShowProposal:
    """The pending-approval context a plan was reached through."""

    id: str
    id_prefix: str
    agent: str
    project: str
    provider_model: str
    age: str
    response_dir: str


@dataclass(frozen=True, slots=True)
class PlanShowRecord:
    """The complete, immutable ``sase plan show`` result."""

    target: PlanShowTarget
    plan: PlanShowPlan
    proposal: PlanShowProposal | None = None
    bead: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Return the complete, stable schema-versioned JSON projection."""
        return {"schema_version": SHOW_SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True, slots=True)
class PlanShowMiss:
    """A target that resolved to no plan.

    ``reason``, when set, replaces the generic ``unknown plan: <target>``
    header with an exact message — used for the omitted-``TARGET`` case so
    the wording matches ``sase plan approve``/``reject``.
    """

    target: str
    suggestions: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlanShowAmbiguityCandidate:
    """One candidate plan offered when a target matches more than one."""

    reference: str
    tier: str | None
    created_at: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class PlanShowAmbiguity:
    """A target that matches more than one plan."""

    target: str
    candidates: tuple[PlanShowAmbiguityCandidate, ...]


__all__ = [
    "SHOW_SCHEMA_VERSION",
    "PlanShowAmbiguity",
    "PlanShowAmbiguityCandidate",
    "PlanShowMiss",
    "PlanShowPhase",
    "PlanShowPlan",
    "PlanShowProposal",
    "PlanShowProvenanceSection",
    "PlanShowRecord",
    "PlanShowSource",
    "PlanShowTarget",
    "PlanShowTargetKind",
    "PlanShowTargetStatus",
    "PlanShowValidation",
]
