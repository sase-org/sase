"""Wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.plan_chain import planner_row_name

from ._artifact_state import (
    artifact_failed_for_identity,
    artifact_is_resolved,
    artifact_succeeded_for_identity,
    done_outcome_from_data,
    family_base_from_meta,
    same_artifact_dir,
)
from ._json_io import read_json_dict
from ._submitted_plans import plan_path_marker, submitted_plan_artifact
from ._types import (
    SUCCESS_OUTCOME,
    ArtifactCandidate,
    FamilyCandidate,
    WaitCandidate,
    WaitDependencyStatus,
)


@dataclass
class WaitDependencyIndex:
    named: dict[str, WaitCandidate]
    workflows: dict[str, list[ArtifactCandidate]]
    families: dict[str, list[ArtifactCandidate]]
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    @classmethod
    def empty(cls) -> WaitDependencyIndex:
        return cls(
            named={},
            workflows={},
            families={},
            clans={},
            artifacts={},
            artifacts_by_dir={},
        )

    @classmethod
    def build(
        cls,
        project_name: str,
        *,
        projects_root: Path | str | None = None,
    ) -> WaitDependencyIndex:
        index = cls.empty()
        for artifact_dir in iter_agent_artifact_dirs(
            project_name,
            "ace-run",
            projects_root=projects_root,
        ):
            meta = read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                index.add(artifact_dir, meta, project_name=project_name)
        return index

    def add(
        self,
        artifact_dir: Path,
        meta: dict[str, Any],
        *,
        project_name: str = "",
    ) -> None:
        done_path = artifact_dir / "done.json"
        done_data = read_json_dict(done_path)
        outcome = done_outcome_from_data(done_data)
        is_resolved = artifact_is_resolved(artifact_dir, meta, outcome)
        is_done = outcome == SUCCESS_OUTCOME
        is_identity_success = artifact_succeeded_for_identity(done_data)
        is_failed = artifact_failed_for_identity(done_data)
        is_queued = (artifact_dir / "waiting.json").exists() and not done_path.exists()
        timestamp = artifact_dir.name

        name = meta.get("name")
        if isinstance(name, str):
            self._record_named_candidate(
                name,
                WaitCandidate(
                    timestamp=timestamp,
                    is_resolved=is_resolved,
                    is_done=is_done,
                    is_failed=is_failed,
                    name=name,
                    project_name=project_name,
                    artifact_dir=str(artifact_dir),
                ),
            )

        # A submitted-and-waiting planner row has no successful done.json, so it
        # never feeds the workflow/family aggregate below. Index it as a
        # resolved named candidate under its canonical ``<base>--plan`` row name
        # so a ``%wait`` on that planner row unblocks while the plan is in
        # review, without making the whole plan chain look complete.
        plan_artifact = submitted_plan_artifact(
            meta=meta,
            plan_path_marker=plan_path_marker(artifact_dir),
            outcome=outcome,
        )
        if plan_artifact is not None:
            self._record_named_candidate(
                plan_artifact.planner_row_name,
                WaitCandidate(timestamp=timestamp, is_resolved=True, is_done=True),
                prefer_on_tie=True,
            )

        workflow_name = meta.get("workflow_name")
        family_name = family_base_from_meta(meta)
        artifact = ArtifactCandidate(
            name=name if isinstance(name, str) else str(workflow_name or ""),
            timestamp=timestamp,
            project_name=project_name,
            artifact_dir=str(artifact_dir),
            parent_timestamp=(
                meta.get("parent_timestamp")
                if isinstance(meta.get("parent_timestamp"), str)
                else None
            ),
            family_name=family_name,
            is_resolved=is_resolved,
            is_done=is_done,
            is_identity_success=is_identity_success,
            is_failed=is_failed,
            is_queued=is_queued,
        )
        if project_name:
            self.artifacts[(project_name, timestamp)] = artifact
        self.artifacts_by_dir[str(artifact_dir)] = artifact

        if isinstance(workflow_name, str):
            self.workflows.setdefault(workflow_name, []).append(artifact)
            if family_name is not None:
                self.families.setdefault(family_name, []).append(artifact)

        clan_name = meta.get("agent_clan")
        if not isinstance(clan_name, str) or not clan_name:
            legacy_family = meta.get("agent_family")
            if (
                meta.get("agent_family_parallel") is True
                and isinstance(legacy_family, str)
                and legacy_family
            ):
                clan_name = legacy_family
        if isinstance(clan_name, str) and clan_name:
            generation = meta.get("agent_clan_generation")
            if not isinstance(generation, str) or not generation:
                generation = artifact.parent_timestamp or artifact.timestamp
            self.clans.setdefault(clan_name, {}).setdefault(generation, []).append(
                artifact
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

    def _record_named_candidate(
        self,
        name: str,
        candidate: WaitCandidate,
        *,
        prefer_on_tie: bool = False,
    ) -> None:
        """Keep the newest named candidate, preferring *candidate* on ties.

        ``prefer_on_tie`` lets a submitted-planner row override the ordinary
        same-artifact candidate it shares a timestamp with.
        """
        latest = self.named.get(name)
        if (
            latest is None
            or candidate.timestamp > latest.timestamp
            or (prefer_on_tie and candidate.timestamp == latest.timestamp)
        ):
            self.named[name] = candidate

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


def build_wait_dependency_index(
    project_name: str,
    *,
    projects_root: Path | str | None = None,
) -> WaitDependencyIndex:
    return WaitDependencyIndex.build(project_name, projects_root=projects_root)
