"""Aggregate entity helpers for the wait-dependency artifact index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._artifact_state import same_artifact_dir
from ._types import ArtifactCandidate, WaitCandidate


@dataclass(frozen=True)
class WaitEntity:
    timestamp: str
    is_resolved: bool
    is_done: bool
    members: tuple[ArtifactCandidate, ...] = ()


class WaitDependencyEntityQueries:
    named: dict[str, WaitCandidate]
    workflows: dict[str, list[ArtifactCandidate]]
    families: dict[str, list[ArtifactCandidate]]
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def _clan_entity(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitEntity | None:
        generations = self.clans.get(name)
        if not generations:
            return None
        generation = max(generations)
        members = tuple(
            self._aggregate_candidates(
                generations[generation],
                exclude_artifact_dir=exclude_artifact_dir,
                exclude_queued=False,
            )
        )
        if not members:
            return None
        return WaitEntity(
            timestamp=max(member.timestamp for member in members),
            is_resolved=all(member.is_resolved for member in members),
            is_done=all(member.is_done for member in members),
            members=members,
        )

    def _family_entity(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitEntity | None:
        extra_present_names = self._excluded_present_names(exclude_artifact_dir)
        family_agents = self._aggregate_candidates(
            self.families.get(name),
            exclude_artifact_dir=exclude_artifact_dir,
            exclude_queued=False,
        )
        if not family_agents:
            return None

        roots = [
            candidate for candidate in family_agents if not candidate.parent_timestamp
        ]
        if roots:
            root = max(roots, key=lambda candidate: candidate.timestamp)
            generation = tuple(self._family_generation(family_agents, root))
            effective_generation, handoffs_present = self._family_handoff_state(
                generation,
                extra_present_names=extra_present_names,
            )
            newest_timestamp = max(
                (candidate.timestamp for candidate in generation),
                default=root.timestamp,
            )
            return WaitEntity(
                timestamp=newest_timestamp,
                is_resolved=(
                    handoffs_present
                    and all(candidate.is_resolved for candidate in effective_generation)
                ),
                is_done=any(candidate.is_done for candidate in effective_generation),
                members=effective_generation,
            )

        effective_family_agents, handoffs_present = self._family_handoff_state(
            tuple(family_agents),
            extra_present_names=extra_present_names,
        )
        return WaitEntity(
            timestamp=max(candidate.timestamp for candidate in family_agents),
            is_resolved=(
                handoffs_present
                and all(candidate.is_resolved for candidate in effective_family_agents)
            ),
            is_done=any(candidate.is_done for candidate in effective_family_agents),
            members=effective_family_agents,
        )

    def _workflow_entity(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitEntity | None:
        workflow_agents = self._aggregate_candidates(
            self.workflows.get(name),
            exclude_artifact_dir=exclude_artifact_dir,
        )
        if not workflow_agents:
            return None

        roots = [
            candidate for candidate in workflow_agents if not candidate.parent_timestamp
        ]
        if not roots:
            latest = max(workflow_agents, key=lambda candidate: candidate.timestamp)
            return WaitEntity(
                timestamp=latest.timestamp,
                is_resolved=latest.is_resolved,
                is_done=latest.is_done,
                members=(latest,),
            )

        root = max(roots, key=lambda candidate: candidate.timestamp)
        generation = (
            root,
            *[
                child
                for child in workflow_agents
                if child.parent_timestamp == root.timestamp
            ],
        )
        return WaitEntity(
            timestamp=root.timestamp,
            is_resolved=all(candidate.is_resolved for candidate in generation),
            is_done=any(candidate.is_done for candidate in generation),
            members=generation,
        )

    def _named_entity(self, name: str) -> WaitEntity | None:
        candidate = self.named.get(name)
        if candidate is None:
            return None
        member = self.artifacts_by_dir.get(candidate.artifact_dir)
        members = (member,) if member is not None else ()
        return WaitEntity(
            timestamp=candidate.timestamp,
            is_resolved=candidate.is_resolved,
            is_done=candidate.is_done,
            members=members,
        )

    def _excluded_member_name(
        self,
        exclude_artifact_dir: str | Path | None,
    ) -> str | None:
        """Return the agent name of the artifact excluded as the waiter itself."""
        if exclude_artifact_dir is None:
            return None
        for candidate in self.artifacts_by_dir.values():
            if same_artifact_dir(candidate.artifact_dir, exclude_artifact_dir):
                return candidate.name or None
        return None

    def _excluded_present_names(
        self,
        exclude_artifact_dir: str | Path | None,
    ) -> frozenset[str]:
        excluded_name = self._excluded_member_name(exclude_artifact_dir)
        return frozenset((excluded_name,)) if excluded_name is not None else frozenset()

    @staticmethod
    def _family_generation(
        candidates: list[ArtifactCandidate],
        root: ArtifactCandidate,
    ) -> list[ArtifactCandidate]:
        """Return every descendant in the root's sequential family chain."""
        generation = [root]
        timestamps = {root.timestamp}
        remaining = [candidate for candidate in candidates if candidate is not root]
        while remaining:
            attached = [
                candidate
                for candidate in remaining
                if candidate.parent_timestamp in timestamps
            ]
            if not attached:
                break
            generation.extend(attached)
            timestamps.update(candidate.timestamp for candidate in attached)
            remaining = [
                candidate for candidate in remaining if candidate not in attached
            ]
        return generation

    @staticmethod
    def _family_members_after_shell_handoffs(
        candidates: tuple[ArtifactCandidate, ...],
        *,
        extra_present_names: frozenset[str] = frozenset(),
    ) -> tuple[ArtifactCandidate, ...]:
        names_in_generation = {
            candidate.name for candidate in candidates
        } | extra_present_names
        return tuple(
            candidate
            for candidate in candidates
            if candidate.shell_followup_agent not in names_in_generation
        )

    @staticmethod
    def _family_shell_handoffs_have_successors(
        candidates: tuple[ArtifactCandidate, ...],
        *,
        extra_present_names: frozenset[str] = frozenset(),
    ) -> bool:
        names_in_generation = {
            candidate.name for candidate in candidates
        } | extra_present_names
        return all(
            candidate.shell_followup_agent is None
            or candidate.shell_followup_agent in names_in_generation
            for candidate in candidates
        )

    @classmethod
    def _family_handoff_state(
        cls,
        candidates: tuple[ArtifactCandidate, ...],
        *,
        extra_present_names: frozenset[str] = frozenset(),
    ) -> tuple[tuple[ArtifactCandidate, ...], bool]:
        return (
            cls._family_members_after_shell_handoffs(
                candidates,
                extra_present_names=extra_present_names,
            ),
            cls._family_shell_handoffs_have_successors(
                candidates,
                extra_present_names=extra_present_names,
            ),
        )

    @staticmethod
    def _aggregate_candidates(
        candidates: list[ArtifactCandidate] | None,
        *,
        exclude_artifact_dir: str | Path | None,
        exclude_queued: bool = True,
    ) -> list[ArtifactCandidate]:
        if not candidates:
            return []
        return [
            candidate
            for candidate in candidates
            if (not exclude_queued or not candidate.is_queued)
            and not same_artifact_dir(candidate.artifact_dir, exclude_artifact_dir)
        ]
