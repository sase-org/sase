"""Process-level memo over the Rust artifact-reference kind catalog.

The catalog is compiled into ``sase_core_rs``, so it never changes within a
process; callers that need every registered kind label (parsing, TUI
completion, syntax highlighting) should go through the memoized accessors
here rather than re-invoking the Rust binding on every keystroke.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, cast

from sase.artifact_ref_models import ArtifactRef
from sase.artifact_ref_operations import (
    artifact_ref_kind_catalog as _artifact_ref_kind_catalog,
    artifact_ref_parse_canonical as _artifact_ref_parse_canonical,
)


ArtifactRefKindStatus = Literal["live", "alias", "deprecated", "historical"]


@dataclass(frozen=True, slots=True)
class _ArtifactRefKindDescriptor:
    """One compiled-in artifact-reference kind, live or historical."""

    kind: str
    display_name: str
    status: ArtifactRefKindStatus
    aliases: tuple[str, ...]
    reserved: bool
    argument_summary: str
    offered_in_completion: bool
    accepts_fragment: bool

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> _ArtifactRefKindDescriptor:
        return cls(
            kind=str(raw["kind"]),
            display_name=str(raw["display_name"]),
            status=cast(ArtifactRefKindStatus, str(raw["status"])),
            aliases=tuple(str(alias) for alias in raw.get("aliases", ())),
            reserved=bool(raw["reserved"]),
            argument_summary=str(raw["argument_summary"]),
            offered_in_completion=bool(raw["offered_in_completion"]),
            accepts_fragment=bool(raw["accepts_fragment"]),
        )


@dataclass(frozen=True, slots=True)
class CanonicalArtifactRef:
    """A parsed reference whose kind label was rewritten to canonical."""

    reference: ArtifactRef
    alias: str | None = None
    diagnostic: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> CanonicalArtifactRef:
        alias = raw.get("alias")
        diagnostic = raw.get("diagnostic")
        return cls(
            reference=ArtifactRef.from_wire(cast(Mapping[str, Any], raw["reference"])),
            alias=None if alias is None else str(alias),
            diagnostic=None if diagnostic is None else str(diagnostic),
        )


@lru_cache(maxsize=1)
def _artifact_ref_kind_descriptors() -> tuple[_ArtifactRefKindDescriptor, ...]:
    """Return every compiled-in artifact-reference kind, live or historical."""
    return tuple(
        _ArtifactRefKindDescriptor.from_wire(raw)
        for raw in _artifact_ref_kind_catalog()
    )


def parsable_artifact_ref_kinds() -> tuple[str, ...]:
    """Return every registered kind label, including aliases and historical kinds."""
    return tuple(descriptor.kind for descriptor in _artifact_ref_kind_descriptors())


def completion_artifact_ref_kinds() -> tuple[str, ...]:
    """Return kind labels that should be offered in ``@`` completion menus."""
    return tuple(
        descriptor.kind
        for descriptor in _artifact_ref_kind_descriptors()
        if descriptor.offered_in_completion
    )


def parse_artifact_ref_canonical(value: str) -> CanonicalArtifactRef:
    """Parse one reference after rewriting only its kind label to canonical."""
    return CanonicalArtifactRef.from_wire(_artifact_ref_parse_canonical(value))


__all__ = [
    "ArtifactRefKindStatus",
    "CanonicalArtifactRef",
    "completion_artifact_ref_kinds",
    "parsable_artifact_ref_kinds",
    "parse_artifact_ref_canonical",
]
