"""Identity dependency queries for the wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from ._types import ArtifactCandidate, AgentSessionCandidate, WaitDependencyStatus

_UNSET: object = object()


def identity_target_is_turn(dependency: Mapping[str, Any]) -> bool:
    """Return whether *dependency* is a v2 turn-scoped identity record."""
    return dependency.get("target") == "turn"


def identity_record_names(dependency: Mapping[str, Any]) -> tuple[str, ...]:
    """Return wait-name aliases that an identity record already covers."""
    names: list[str] = []
    for key in ("name", "requested", "turn_name"):
        value = dependency.get(key)
        if isinstance(value, str) and value and value not in names:
            names.append(value)
    return tuple(names)


class _IdentityQueryIndex(Protocol):
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def agent_session_candidate_for_root(
        self,
        root: ArtifactCandidate,
        *,
        exclude_artifact_dir: str | Path | None = None,
        exclude_slot_queued: bool = False,
    ) -> AgentSessionCandidate | None: ...

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
        if identity_target_is_turn(dependency):
            return self._pinned_turn_status(
                dependency,
                candidate,
                exclude_artifact_dir=exclude_artifact_dir,
            )
        if candidate is None:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
            )

        agent_session_candidate = index.agent_session_candidate_for_root(
            candidate,
            exclude_artifact_dir=exclude_artifact_dir,
        )
        if agent_session_candidate is not None:
            if agent_session_candidate.is_failed:
                return self._identity_name_fallback_status(
                    dependency,
                    exclude_artifact_dir=exclude_artifact_dir,
                    newer_than=agent_session_candidate.timestamp,
                )
            if (
                agent_session_candidate.is_resolved
                and agent_session_candidate.is_identity_success
            ):
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

    def _pinned_turn_status(
        self,
        dependency: Mapping[str, Any],
        candidate: ArtifactCandidate | None,
        *,
        exclude_artifact_dir: str | Path | None,
    ) -> WaitDependencyStatus:
        """Evaluate a turn record against only the pinned candidate.

        Never expands through :meth:`agent_session_candidate_for_root`. A
        pinned gate or monitor settles when its own done marker lands,
        including ``gated`` / ``monitored`` outcomes that are not session
        identity-success. Failure fallback is scoped to ``turn_name``.
        """
        fallback_name = dependency.get("turn_name")
        if candidate is None:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
                name=fallback_name,
            )
        if candidate.is_failed:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
                newer_than=candidate.timestamp,
                name=fallback_name,
            )
        if _pinned_turn_is_settled(candidate):
            return WaitDependencyStatus("resolved")
        return WaitDependencyStatus("waiting")

    def _identity_name_fallback_status(
        self,
        dependency: Mapping[str, Any],
        *,
        exclude_artifact_dir: str | Path | None,
        newer_than: str | None = None,
        name: object = _UNSET,
    ) -> WaitDependencyStatus:
        index = cast(_IdentityQueryIndex, self)
        resolved_name = dependency.get("name") if name is _UNSET else name
        if (
            isinstance(resolved_name, str)
            and resolved_name
            and index.is_resolved(
                resolved_name,
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


def _pinned_turn_is_settled(candidate: ArtifactCandidate) -> bool:
    """Return whether the pinned turn itself has ended.

    Identity-success outcomes cover completed agent turns. A done marker
    also settles gated and monitored turns, which are not identity-success
    for the owning session aggregate.
    """
    return (
        candidate.is_identity_success
        or candidate.has_done_marker
        or candidate.archived_completion is not None
        or candidate.is_resolved
    )
