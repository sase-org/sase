"""Shared value types for the artifact-link derivation rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DerivableDocument:
    """One artifact ref paired with the file a derivation rule may read."""

    ref: str
    path: Path


@dataclass(frozen=True, slots=True)
class DerivedLinkCandidate:
    """One host-derived artifact-link row a call site may choose to persist.

    Carries only what a derivation rule can know from the artifact itself.
    A call site fills in ``created_by``, ``created_at``, and ``uses`` when it
    turns this into a persisted row.
    """

    source_ref: str
    relation: str
    target_ref: str
    description: str
    origin: str = "derived"
