"""Artifact-reference resolution result models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_ref_wire import (
    ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION,
    ArtifactRefResolutionStatus,
)


@dataclass(frozen=True, slots=True)
class ArtifactRefResolution:
    schema_version: int
    status: ArtifactRefResolutionStatus
    rendered: str
    locator: str | None
    resolved_path: Path | None
    candidates: tuple[str, ...]
    diagnostic: str | None = None

    @property
    def best_path(self) -> Path | None:
        if self.resolved_path is not None:
            return self.resolved_path
        if not self.candidates or self.status not in {"ambiguous", "missing"}:
            return None
        return Path(self.candidates[0])


@dataclass(frozen=True, slots=True)
class ArtifactRefPathFilterResult:
    """Result from the Rust-owned artifact-reference path filter."""

    schema_version: int
    kind: str
    allowed: tuple[str, ...]
    filtered: tuple[str, ...]

    @classmethod
    def from_wire(
        cls,
        raw: Mapping[str, Any],
        *,
        record: str = "artifact-reference path filter",
    ) -> ArtifactRefPathFilterResult:
        version = int(raw["schema_version"])
        if version != ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION:
            raise RuntimeError(
                f"sase_core_rs returned an unsupported {record} wire: {version}"
            )
        return cls(
            schema_version=version,
            kind=str(raw["kind"]),
            allowed=tuple(str(item) for item in raw.get("allowed", ())),
            filtered=tuple(str(item) for item in raw.get("filtered", ())),
        )


__all__ = [
    "ArtifactRefPathFilterResult",
    "ArtifactRefResolution",
]
