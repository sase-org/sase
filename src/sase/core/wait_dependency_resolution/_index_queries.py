"""Candidate queries for the wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.plan_chain import planner_row_name

from ._artifact_state import same_artifact_dir
from ._tribe_binding import TribeMemberRow, resolve_tribe_wait_binding
from ._types import (
    ArtifactCandidate,
    FamilyCandidate,
    TribeCandidate,
    WaitCandidate,
    WaitDependencyStatus,
)


class WaitDependencyIndexQueries:
    """Read-side operations shared by :class:`WaitDependencyIndex`."""

    named: dict[str, WaitCandidate]
    workflows: dict[str, list[ArtifactCandidate]]
    families: dict[str, list[ArtifactCandidate]]
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    tribes: dict[str, list[ArtifactCandidate]]
    effective_clan_tribes: dict[tuple[str, str], str]
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def tribe_candidate(
        self,
        tribe: str,
        *,
        newer_than: str | None,
        exclude_artifact_dir: str | Path | None = None,
    ) -> TribeCandidate | None:
        """Return the earliest complete entity launched after *newer_than*.

        A tribe-assigned clan member enrolls its whole generation. Clan entities use
        the generation's earliest member launch as their timestamp and resolve
        only once the same member aggregate used by clan waits is successful.
        """
        if newer_than is None:
            return None

        direct_tribes_by_artifact: dict[str, set[str]] = {}
        for direct_tribe, artifacts in self.tribes.items():
            for artifact in artifacts:
                direct_tribes_by_artifact.setdefault(artifact.artifact_dir, set()).add(
                    direct_tribe
                )

        rows: list[TribeMemberRow] = []
        for artifact in self.artifacts_by_dir.values():
            direct_tribes = direct_tribes_by_artifact.get(artifact.artifact_dir)
            for member_tribe in direct_tribes or (None,):
                rows.append(
                    TribeMemberRow(
                        tribe=member_tribe,
                        launch_timestamp=artifact.timestamp,
                        identity=artifact.artifact_dir,
                        name=artifact.name,
                        clan_name=artifact.clan_name,
                        clan_generation=artifact.clan_generation,
                        effective_clan_tribe=self.effective_clan_tribes.get(
                            (artifact.clan_name, artifact.clan_generation)
                        )
                        if artifact.clan_name is not None
                        and artifact.clan_generation is not None
                        else None,
                        is_complete=artifact.is_resolved and artifact.is_done,
                        is_terminal=(
                            artifact.is_done
                            or artifact.is_failed
                            or artifact.is_identity_success
                        ),
                    )
                )

        exclude_identity = next(
            (
                artifact.artifact_dir
                for artifact in self.artifacts_by_dir.values()
                if same_artifact_dir(artifact.artifact_dir, exclude_artifact_dir)
            ),
            None,
        )
        binding = resolve_tribe_wait_binding(
            tribe,
            rows,
            newer_than=newer_than,
            exclude_identity=exclude_identity,
        )
        if (
            binding.state != "bound"
            or binding.kind is None
            or binding.name is None
            or binding.timestamp is None
        ):
            return None

        if binding.kind == "agent":
            members: tuple[ArtifactCandidate, ...]
            standalone = (
                self.artifacts_by_dir.get(binding.identity)
                if binding.identity is not None
                else None
            )
            members = (standalone,) if standalone is not None else ()
        else:
            assert binding.generation is not None
            members = tuple(
                sorted(
                    self.clans.get(binding.name, {}).get(binding.generation, []),
                    key=lambda member: member.timestamp,
                )
            )
        if not members:
            return None
        return TribeCandidate(
            tribe=tribe,
            kind=binding.kind,
            name=binding.name,
            generation=binding.generation,
            timestamp=binding.timestamp,
            members=members,
        )

    def clan_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
        """Return aggregate completion for the newest rootless clan generation."""
        generations = self.clans.get(name)
        if not generations:
            return None
        generation = max(generations)
        members = self._aggregate_candidates(
            generations[generation],
            exclude_artifact_dir=exclude_artifact_dir,
            exclude_queued=False,
        )
        if not members:
            return None
        return FamilyCandidate(
            timestamp=max(member.timestamp for member in members),
            is_resolved=all(member.is_resolved for member in members),
            is_done=all(member.is_done for member in members),
            is_identity_success=all(member.is_identity_success for member in members),
            is_failed=any(member.is_failed for member in members),
        )

    def family_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
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
            generation = self._family_generation(family_agents, root)
            newest_timestamp = max(
                (candidate.timestamp for candidate in generation),
                default=root.timestamp,
            )
            return FamilyCandidate(
                timestamp=newest_timestamp,
                is_resolved=all(candidate.is_resolved for candidate in generation),
                is_done=any(candidate.is_done for candidate in generation),
                is_identity_success=any(
                    candidate.is_identity_success for candidate in generation
                ),
                is_failed=any(candidate.is_failed for candidate in generation),
            )

        # Legacy recovery path: if only child artifacts remain, judge the known
        # generation by all retained family members.
        newest_timestamp = max(candidate.timestamp for candidate in family_agents)
        return FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=all(candidate.is_resolved for candidate in family_agents),
            is_done=any(candidate.is_done for candidate in family_agents),
            is_identity_success=any(
                candidate.is_identity_success for candidate in family_agents
            ),
            is_failed=any(candidate.is_failed for candidate in family_agents),
        )

    def family_candidate_for_root(
        self,
        root: ArtifactCandidate,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
        if root.parent_timestamp:
            return None
        family_name = root.family_name or root.name
        if not family_name:
            return None
        family_agents = self._aggregate_candidates(
            self.families.get(family_name),
            exclude_artifact_dir=exclude_artifact_dir,
        )
        if not family_agents:
            return None
        generation = self._family_generation(family_agents, root)
        if not generation:
            return None
        newest_timestamp = max(candidate.timestamp for candidate in generation)
        return FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=all(candidate.is_resolved for candidate in generation),
            is_done=any(candidate.is_done for candidate in generation),
            is_identity_success=any(
                candidate.is_identity_success for candidate in generation
            ),
            is_failed=any(candidate.is_failed for candidate in generation),
        )

    def workflow_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitCandidate | None:
        # Workflow-name aggregates intentionally retain the queued exclusion:
        # including sequential workflow steps here can deadlock their promotion.
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
            # Some older/renamed runs may only retain workflow_name on child
            # artifacts. Preserve the recovery path by judging the newest such
            # artifact, while still requiring an explicit successful done marker.
            latest = max(workflow_agents, key=lambda candidate: candidate.timestamp)
            return WaitCandidate(
                timestamp=latest.timestamp,
                is_resolved=latest.is_resolved,
                is_done=latest.is_done,
            )

        root = max(roots, key=lambda candidate: candidate.timestamp)
        generation = [
            root,
            *[
                child
                for child in workflow_agents
                if child.parent_timestamp == root.timestamp
            ],
        ]
        return WaitCandidate(
            timestamp=root.timestamp,
            is_resolved=all(candidate.is_resolved for candidate in generation),
            is_done=any(candidate.is_done for candidate in generation),
        )

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

    def _planner_row_candidate(self, name: str) -> WaitCandidate | None:
        """Return a submitted-planner-row candidate for a legacy-spelled wait.

        A ``%wait`` on a legacy planner-row spelling (``base.plan``) resolves to
        the canonical ``base--plan`` named candidate. Canonical names already
        hit ``self.named`` directly, so they are skipped here.
        """
        alias = planner_row_name(name, include_legacy_dash=True)
        if alias is None or alias == name:
            return None
        return self.named.get(alias)

    def is_resolved(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
        newer_than: str | None = None,
    ) -> bool:
        if name.startswith("@"):
            try:
                tribe = parse_tribe_reference(name)
            except InvalidTribeError:
                return False
            assert tribe is not None
            return (
                self.tribe_candidate(
                    tribe,
                    newer_than=newer_than,
                    exclude_artifact_dir=exclude_artifact_dir,
                )
                is not None
            )

        candidates = [
            candidate
            for candidate in (
                self.clan_candidate(name, exclude_artifact_dir=exclude_artifact_dir),
                self.family_candidate(name, exclude_artifact_dir=exclude_artifact_dir),
                self.workflow_candidate(
                    name,
                    exclude_artifact_dir=exclude_artifact_dir,
                ),
                self.named.get(name),
                self._planner_row_candidate(name),
            )
            if candidate is not None
        ]
        if not candidates:
            return False

        latest = max(candidates, key=lambda candidate: candidate.timestamp)
        return (
            (newer_than is None or latest.timestamp > newer_than)
            and latest.is_resolved
            and latest.is_done
        )

    def identity_status(
        self,
        dependency: Mapping[str, Any],
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitDependencyStatus:
        candidate = self._identity_candidate(dependency)
        if candidate is None:
            return self._identity_name_fallback_status(
                dependency,
                exclude_artifact_dir=exclude_artifact_dir,
            )

        family_candidate = self.family_candidate_for_root(
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
        name = dependency.get("name")
        if (
            isinstance(name, str)
            and name
            and self.is_resolved(
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
