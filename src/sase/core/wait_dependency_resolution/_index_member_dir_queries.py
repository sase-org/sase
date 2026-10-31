"""Raw artifact membership queries for wait-release confirmation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference

from ._artifact_state import artifact_dir_key
from ._index_fork_queries import fork_source_follows_promotion
from ._index_identity_queries import identity_record_names, identity_target_is_turn
from ._types import ArtifactCandidate, WaitCandidate


class _MemberDirQueryIndex(Protocol):
    def stored_tribe_names(self) -> tuple[str, ...]: ...

    def _planner_row_candidate(self, name: str) -> WaitCandidate | None: ...

    def _identity_candidate(
        self,
        dependency: Mapping[str, Any],
    ) -> ArtifactCandidate | None: ...

    def _hood_candidates(
        self,
        hood: str,
        *,
        launched_at_or_before: str | None,
        exclude_artifact_dir: str | Path | None = None,
    ) -> tuple[ArtifactCandidate, ...]: ...


class WaitDependencyMemberDirQueries:
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    tribes: dict[str, list[ArtifactCandidate]]
    effective_clan_tribes: dict[tuple[str, str], str]
    artifacts_by_dir: dict[str, ArtifactCandidate]
    agent_sessions: dict[str, list[ArtifactCandidate]]
    workflows: dict[str, list[ArtifactCandidate]]
    named: dict[str, WaitCandidate]

    def dependency_member_dirs(
        self,
        wait_names: Iterable[object],
        wait_identity_deps: Iterable[object] = (),
        resolved_deps: Iterable[object] = (),
        *,
        wait_fork_sources: Iterable[object] = (),
        wait_hoods: Iterable[object] = (),
        self_artifact_dir: str | Path | None = None,
    ) -> frozenset[str]:
        """Return the raw artifact membership relevant to a wait resolution.

        This deliberately precedes the aggregate entities' handoff and queued-member
        filtering.  Release confirmation needs to notice a newly-created successor
        even when the resolving view would filter its predecessor out of the final
        agent-session aggregate.
        """
        resolved_items = tuple(resolved_deps)
        excluded_key = (
            artifact_dir_key(str(self_artifact_dir))
            if self_artifact_dir is not None
            else None
        )
        member_dirs: dict[str, str] = {}
        index = cast(_MemberDirQueryIndex, self)

        def add_candidates(candidates: Iterable[ArtifactCandidate] | None) -> None:
            if candidates is None:
                return
            for candidate in candidates:
                key = artifact_dir_key(candidate.artifact_dir)
                if excluded_key is None or key != excluded_key:
                    member_dirs.setdefault(key, candidate.artifact_dir)

        def add_named_candidate(candidate: WaitCandidate | None) -> None:
            if candidate is None:
                return
            if candidate.artifact_dir:
                key = artifact_dir_key(candidate.artifact_dir)
                if excluded_key is None or key != excluded_key:
                    member_dirs.setdefault(key, candidate.artifact_dir)
                return
            # Submitted planner-row aliases retain their source artifact dir so
            # scoped indexes can recover membership without scanning every row
            # for a timestamp collision across projects.

        def add_name_members(name: str) -> None:
            if name.startswith("@"):
                try:
                    tribe = parse_tribe_reference(
                        name,
                        stored_tribes=index.stored_tribe_names(),
                    )
                except InvalidTribeError:
                    return
                assert tribe is not None
                add_candidates(self.tribes.get(tribe))
                add_candidates(
                    artifact
                    for artifact in self.artifacts_by_dir.values()
                    if artifact.clan_name is not None
                    and artifact.clan_generation is not None
                    and self.effective_clan_tribes.get(
                        (artifact.clan_name, artifact.clan_generation)
                    )
                    == tribe
                )
                return
            add_candidates(self.agent_sessions.get(name))
            add_candidates(self.workflows.get(name))
            for generation in self.clans.get(name, {}).values():
                add_candidates(generation)
            add_named_candidate(self.named.get(name))
            add_named_candidate(index._planner_row_candidate(name))

        def add_candidate_members(candidate: ArtifactCandidate) -> None:
            add_candidates((candidate,))
            agent_session_name = candidate.agent_session_name or candidate.name
            if agent_session_name:
                add_candidates(self.agent_sessions.get(agent_session_name))
            if candidate.clan_name is not None:
                generations = self.clans.get(candidate.clan_name, {})
                if candidate.clan_generation is not None:
                    add_candidates(generations.get(candidate.clan_generation))
                else:
                    for generation in generations.values():
                        add_candidates(generation)

        identity_names: set[str] = set()
        for dependency in wait_identity_deps:
            if not isinstance(dependency, Mapping):
                continue
            identity_names.update(identity_record_names(dependency))
            if _identity_dependency_is_memoized(dependency, resolved_items):
                continue
            candidate = index._identity_candidate(dependency)
            if identity_target_is_turn(dependency):
                if candidate is None:
                    turn_name = dependency.get("turn_name")
                    if isinstance(turn_name, str) and turn_name:
                        add_name_members(turn_name)
                else:
                    add_candidates((candidate,))
                continue
            name = dependency.get("name")
            if candidate is None:
                if isinstance(name, str) and name:
                    add_name_members(name)
            else:
                add_candidate_members(candidate)

        fork_source_names: set[str] = set()
        for dependency in wait_fork_sources:
            if not isinstance(dependency, Mapping):
                continue
            if dependency.get("history_only"):
                continue
            name = dependency.get("name")
            target_is_turn = dependency.get("target") == "turn"
            if not target_is_turn and isinstance(name, str) and name:
                fork_source_names.add(name)
            if _dependency_label(dependency) in resolved_items:
                continue
            candidate = index._identity_candidate(dependency)
            if candidate is not None:
                if target_is_turn:
                    add_candidates((candidate,))
                else:
                    add_candidate_members(candidate)
                if not target_is_turn and fork_source_follows_promotion(
                    dependency, candidate
                ):
                    # A healed bare-name record releases on the whole session,
                    # so confirmation must see every session member even when
                    # the resolving view predates the promotion.
                    session_name = candidate.agent_session_name
                    if session_name:
                        add_candidates(self.agent_sessions.get(session_name))
            kind = dependency.get("kind")
            if kind == "clan" and isinstance(name, str) and name:
                generations = self.clans.get(name, {})
                generation = dependency.get("generation")
                if isinstance(generation, str) and generation:
                    add_candidates(generations.get(generation))
                else:
                    for members in generations.values():
                        add_candidates(members)
            elif (
                candidate is None
                and not target_is_turn
                and isinstance(name, str)
                and name
            ):
                add_name_members(name)

        for name in wait_names:
            if (
                not isinstance(name, str)
                or name in identity_names
                or name in fork_source_names
                or name in resolved_items
            ):
                continue
            add_name_members(name)

        waiter_launch_cutoff = (
            Path(self_artifact_dir).name if self_artifact_dir is not None else None
        )
        for hood in wait_hoods:
            if isinstance(hood, str) and hood:
                add_candidates(
                    index._hood_candidates(
                        hood,
                        launched_at_or_before=waiter_launch_cutoff,
                        exclude_artifact_dir=self_artifact_dir,
                    )
                )

        return frozenset(member_dirs)


def _identity_dependency_is_memoized(
    dependency: Mapping[str, object],
    resolved_deps: Iterable[object],
) -> bool:
    for memo in resolved_deps:
        if not isinstance(memo, Mapping):
            continue
        artifact_dir = dependency.get("artifact_dir")
        memo_artifact_dir = memo.get("artifact_dir")
        if (
            isinstance(artifact_dir, str)
            and artifact_dir
            and isinstance(memo_artifact_dir, str)
            and memo_artifact_dir
            and artifact_dir_key(artifact_dir) == artifact_dir_key(memo_artifact_dir)
        ):
            return True
        project_name = dependency.get("project_name")
        timestamp = dependency.get("timestamp")
        if (
            isinstance(project_name, str)
            and project_name
            and isinstance(timestamp, str)
            and timestamp
            and memo.get("project_name") == project_name
            and memo.get("timestamp") == timestamp
        ):
            return True
    return False


def _dependency_label(dependency: Mapping[str, object]) -> str:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        return artifact_dir
    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if (
        isinstance(project_name, str)
        and project_name
        and isinstance(timestamp, str)
        and timestamp
    ):
        return f"{project_name}:{timestamp}"
    name = dependency.get("name")
    if isinstance(name, str) and name:
        return name
    return "<artifact dependency>"
