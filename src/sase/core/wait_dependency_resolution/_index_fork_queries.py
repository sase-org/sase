"""Fork-source queries for the wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from ._index_entities import WaitEntity
from ._types import ArtifactCandidate, FamilyCandidate, WaitDependencyStatus


class _ForkQueryIndex(Protocol):
    clans: dict[str, dict[str, list[ArtifactCandidate]]]

    def _aggregate_candidates(
        self,
        candidates: list[ArtifactCandidate] | None,
        *,
        exclude_artifact_dir: str | Path | None,
        exclude_queued: bool = True,
    ) -> list[ArtifactCandidate]: ...

    def _clan_entity(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitEntity | None: ...

    def _family_entity(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitEntity | None: ...

    def _identity_candidate(
        self,
        dependency: Mapping[str, Any],
    ) -> ArtifactCandidate | None: ...

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

    def terminal_blocking_artifacts_for_name(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
        newer_than: str | None = None,
    ) -> tuple[ArtifactCandidate, ...]: ...


class WaitDependencyForkQueries:
    clans: dict[str, dict[str, list[ArtifactCandidate]]]

    def fork_source_status(
        self,
        dependency: Mapping[str, Any],
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitDependencyStatus:
        """Resolve the terminal-aware dependency implied by one ``#fork`` source."""
        index = cast(_ForkQueryIndex, self)
        kind = _mapping_string(dependency, "kind")
        name = _mapping_string(dependency, "name")
        if kind == "agent":
            candidate = index._identity_candidate(dependency)
            if candidate is not None:
                return _fork_status(_candidate_terminal_for_fork(candidate))
            return self._fork_name_fallback_status(
                name,
                exclude_artifact_dir=exclude_artifact_dir,
            )
        if kind == "family":
            candidate = index._identity_candidate(dependency)
            if candidate is not None:
                family = index.family_candidate_for_root(
                    candidate,
                    exclude_artifact_dir=exclude_artifact_dir,
                )
                if family is not None:
                    return _fork_status(
                        (family.is_resolved and family.is_done) or family.is_failed
                    )
            return self._fork_family_name_status(
                name,
                exclude_artifact_dir=exclude_artifact_dir,
            )
        if kind == "clan":
            return self._fork_clan_status(
                name,
                _mapping_string(dependency, "generation"),
                exclude_artifact_dir=exclude_artifact_dir,
            )
        if kind == "proc":
            return _fork_status(_proc_source_is_terminal(dependency))
        return self._fork_name_fallback_status(
            name,
            exclude_artifact_dir=exclude_artifact_dir,
        )

    def _fork_family_name_status(
        self,
        name: str | None,
        *,
        exclude_artifact_dir: str | Path | None,
    ) -> WaitDependencyStatus:
        index = cast(_ForkQueryIndex, self)
        if not name:
            return WaitDependencyStatus("waiting")
        entity = index._family_entity(name, exclude_artifact_dir=exclude_artifact_dir)
        if entity is None:
            return self._fork_name_fallback_status(
                name,
                exclude_artifact_dir=exclude_artifact_dir,
            )
        return _fork_status(_entity_terminal_for_fork(entity))

    def _fork_clan_status(
        self,
        name: str | None,
        generation: str | None,
        *,
        exclude_artifact_dir: str | Path | None,
    ) -> WaitDependencyStatus:
        index = cast(_ForkQueryIndex, self)
        if not name:
            return WaitDependencyStatus("waiting")
        if generation:
            members = tuple(
                index._aggregate_candidates(
                    self.clans.get(name, {}).get(generation),
                    exclude_artifact_dir=exclude_artifact_dir,
                    exclude_queued=False,
                )
            )
            if not members:
                return WaitDependencyStatus("waiting")
            return _fork_status(
                all(_candidate_terminal_for_fork(member) for member in members)
            )
        entity = index._clan_entity(name, exclude_artifact_dir=exclude_artifact_dir)
        if entity is None:
            return WaitDependencyStatus("waiting")
        return _fork_status(_entity_terminal_for_fork(entity))

    def _fork_name_fallback_status(
        self,
        name: str | None,
        *,
        exclude_artifact_dir: str | Path | None,
    ) -> WaitDependencyStatus:
        index = cast(_ForkQueryIndex, self)
        if not name:
            return WaitDependencyStatus("waiting")
        if index.is_resolved(name, exclude_artifact_dir=exclude_artifact_dir):
            return WaitDependencyStatus("resolved")
        if index.terminal_blocking_artifacts_for_name(
            name,
            exclude_artifact_dir=exclude_artifact_dir,
        ):
            return WaitDependencyStatus("resolved")
        return WaitDependencyStatus("waiting")


def _mapping_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _fork_status(resolved: bool) -> WaitDependencyStatus:
    return WaitDependencyStatus("resolved" if resolved else "waiting")


def _candidate_terminal_for_fork(candidate: ArtifactCandidate) -> bool:
    return candidate.is_done or candidate.is_failed


def _entity_terminal_for_fork(entity: WaitEntity) -> bool:
    return bool(entity.members) and all(
        _candidate_terminal_for_fork(member) for member in entity.members
    )


def _proc_source_is_terminal(dependency: Mapping[str, Any]) -> bool:
    proc_id = _mapping_string(dependency, "proc_id")
    if proc_id is None:
        return False
    try:
        from sase.procs.models import TERMINAL_PROC_STATUSES
        from sase.procs.store import get_proc

        proc = get_proc(proc_id)
    except Exception:
        return False
    return bool(proc is not None and proc.status in TERMINAL_PROC_STATUSES)
