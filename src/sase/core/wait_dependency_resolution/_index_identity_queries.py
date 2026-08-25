"""Identity dependency queries for the wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from ._types import ArtifactCandidate, FamilyCandidate, WaitDependencyStatus


class _IdentityQueryIndex(Protocol):
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def family_candidate_for_root(
        self,
        root: ArtifactCandidate,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None: ...

    def is_resolved(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
        newer_than: str | None = None,
    ) -> bool: ...


class WaitDependencyIdentityQueries:
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def identity_status(
        self,
        dependency: Mapping[str, Any],
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitDependencyStatus:
        index = cast(_IdentityQueryIndex, self)
        candidate = self._identity_candidate(dependency)
        if candidate is None:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
            )

        family_candidate = index.family_candidate_for_root(
            candidate,
            exclude_artifact_dir=exclude_artifact_dir,
        )
        if family_candidate is not None:
            if family_candidate.is_failed:
                return self._identity_name_fallback_status(
                    dependency,
                    exclude_artifact_dir=exclude_artifact_dir,
                    newer_than=family_candidate.timestamp,
                )
            if family_candidate.is_resolved and family_candidate.is_identity_success:
                return WaitDependencyStatus("resolved")
            return WaitDependencyStatus("waiting")

        if candidate.is_failed:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
                newer_than=candidate.timestamp,
            )
        if candidate.is_identity_success:
            return WaitDependencyStatus("resolved")
        return WaitDependencyStatus("waiting")

    def _identity_name_fallback_status(
        self,
        dependency: Mapping[str, Any],
        *,
        exclude_artifact_dir: str | Path | None,
        newer_than: str | None = None,
    ) -> WaitDependencyStatus:
        index = cast(_IdentityQueryIndex, self)
        name = dependency.get("name")
        if (
            isinstance(name, str)
            and name
            and index.is_resolved(
                name,
                exclude_artifact_dir=exclude_artifact_dir,
                newer_than=newer_than,
            )
        ):
            return WaitDependencyStatus("resolved")
        return WaitDependencyStatus("waiting")

    def _identity_candidate(
        self,
        dependency: Mapping[str, Any],
    ) -> ArtifactCandidate | None:
        artifact_dir = dependency.get("artifact_dir")
        if isinstance(artifact_dir, str) and artifact_dir:
            candidate = self.artifacts_by_dir.get(artifact_dir)
            if candidate is not None:
                return candidate

        project_name = dependency.get("project_name")
        timestamp = dependency.get("timestamp")
        if isinstance(project_name, str) and isinstance(timestamp, str):
            return self.artifacts.get((project_name, timestamp))
        return None
