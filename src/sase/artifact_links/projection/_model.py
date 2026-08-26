"""Shared value types for the artifact-link projection rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectedEdge:
    """One artifact-link row a projection rule recomputed from an owned fact."""

    source_ref: str
    relation: str
    target_ref: str
    description: str
    rule_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    """Store-scoped facts every projection rule reads from, never mutates.

    Built strictly from an :class:`ArtifactLinkStore`'s own roots, so a store
    with no repo inventory and no agents sidecar yields every field ``None``
    and every rule becomes a no-op.
    """

    project_key: str
    primary_repo_root: Path | None
    primary_repo_name: str | None
    agents_sidecar_root: Path | None
