"""Artifact-entry models for artifact-reference providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal


ArtifactEntryOrigin = Literal["prompt_ref", "agent_artifact", "both"]


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """A normalized artifact-entry, mirroring ``ArtifactEntryWire``.

    Constructed by the Python builtin-entry resolvers (stitch/patch/bead/agent);
    always pass a freshly built entry through :func:`artifact_ref_entry_validate`
    before use.
    """

    stable_id: str
    ref_kind: str
    canonical_argument: str
    display_label: str
    origin: ArtifactEntryOrigin
    project_display_name: str | None = None
    repository: str | None = None
    repo_relative_path: str | None = None
    captured_revision: str | None = None
    captured_digest: str | None = None
    logical_path: str | None = None
    properties: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def to_wire(self) -> dict[str, object]:
        # Lazy import: artifact_ref_operations imports ArtifactEntry through the facade.
        from sase.artifact_ref_operations import artifact_ref_entry_wire_schema_version

        raw: dict[str, object] = {
            "schema_version": artifact_ref_entry_wire_schema_version(),
            "stable_id": self.stable_id,
            "ref_kind": self.ref_kind,
            "canonical_argument": self.canonical_argument,
            "display_label": self.display_label,
            "properties": dict(self.properties),
            "origin": self.origin,
        }
        for name in (
            "project_display_name",
            "repository",
            "repo_relative_path",
            "captured_revision",
            "captured_digest",
            "logical_path",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


__all__ = [
    "ArtifactEntry",
    "ArtifactEntryOrigin",
]
