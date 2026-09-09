"""Document-source target resolution models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.artifact_ref_wire import (
    ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION,
    ArtifactRefTargetFailureCategory,
    optional_str,
)


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentOwner:
    """Provenance for a scanned document link's own source.

    Lets an unqualified source path resolve in the repository that actually
    owns the document naming it, rather than the viewer's cwd. Every field is
    optional: absent provenance falls back to searching every repository in
    the caller's resolution context. ``path_globs`` is an optional source-path
    policy for that resolver; the host currently has no repository-source
    filter of its own, so production callers omit it. Typed document
    filtering remains on document roots.
    """

    source_reference: str | None = None
    project_key: str | None = None
    repository: str | None = None
    revision: str | None = None
    source_directory: str | None = None
    checkout_candidates: tuple[Path, ...] = ()
    # Optional source-path policy for ``resolve_document_source_target``.
    # ``None`` means the host has no repository-source filter (typed document
    # ``path_globs`` stay on document roots). ``()`` is an explicit empty
    # policy and denies every path.
    path_globs: tuple[str, ...] | None = None

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "checkout_candidates": [str(path) for path in self.checkout_candidates],
        }
        for name in (
            "source_reference",
            "project_key",
            "repository",
            "revision",
            "source_directory",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        if self.path_globs is not None:
            raw["path_globs"] = list(self.path_globs)
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefTargetCandidate:
    """One inspected or selected candidate, kept as resolution evidence."""

    path: str
    evidence: str
    repository: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefTargetCandidate:
        return cls(
            path=str(raw["path"]),
            evidence=str(raw["evidence"]),
            repository=optional_str(raw.get("repository")),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefTargetResolution:
    """The outcome of resolving one document-owned source-path target."""

    schema_version: int
    status: str
    resolved_path: Path | None
    repository: str | None
    revision: str | None
    candidates: tuple[ArtifactRefTargetCandidate, ...]
    failure_category: ArtifactRefTargetFailureCategory | None
    retryable: bool
    diagnostic: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefTargetResolution:
        version = int(raw["schema_version"])
        if version != ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION:
            raise RuntimeError(
                "sase_core_rs returned an unsupported artifact-reference "
                f"target resolution wire: {version}"
            )
        resolved_path = raw.get("resolved_path")
        failure_category = raw.get("failure_category")
        return cls(
            schema_version=version,
            status=str(raw["status"]),
            resolved_path=None if resolved_path is None else Path(str(resolved_path)),
            repository=optional_str(raw.get("repository")),
            revision=optional_str(raw.get("revision")),
            candidates=tuple(
                ArtifactRefTargetCandidate.from_wire(cast(Mapping[str, Any], item))
                for item in raw.get("candidates", ())
            ),
            failure_category=(
                None
                if failure_category is None
                else cast(ArtifactRefTargetFailureCategory, str(failure_category))
            ),
            retryable=bool(raw["retryable"]),
            diagnostic=optional_str(raw.get("diagnostic")),
        )


__all__ = [
    "ArtifactRefDocumentOwner",
    "ArtifactRefTargetCandidate",
    "ArtifactRefTargetResolution",
]
