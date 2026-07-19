"""Wait-dependency artifact index."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_clan_tribe import ClanTribeMemberWire, resolve_clan_tribe
from sase.core.agent_tribe import (
    InvalidTribeError,
    RawAgentTribeIdentity,
    canonicalize_agent_tribe_metadata,
    load_raw_agent_tribes,
    validate_tribe_name,
)

from ._artifact_state import (
    artifact_failed_for_identity,
    artifact_is_resolved,
    artifact_succeeded_for_identity,
    done_outcome_from_data,
    family_base_from_meta,
)
from ._index_queries import WaitDependencyIndexQueries
from ._json_io import read_json_dict
from ._submitted_plans import plan_path_marker, submitted_plan_artifact
from ._types import (
    SUCCESS_OUTCOME,
    ArtifactCandidate,
    WaitCandidate,
)


@dataclass
class WaitDependencyIndex(WaitDependencyIndexQueries):
    named: dict[str, WaitCandidate]
    workflows: dict[str, list[ArtifactCandidate]]
    families: dict[str, list[ArtifactCandidate]]
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    tribes: dict[str, list[ArtifactCandidate]]
    effective_clan_tribes: dict[tuple[str, str], str]
    agent_tribes: dict[RawAgentTribeIdentity, str]
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    @classmethod
    def empty(
        cls,
        *,
        agent_tribes_path: Path | str | None = None,
        legacy_agent_tags_path: Path | str | None = None,
    ) -> WaitDependencyIndex:
        return cls(
            named={},
            workflows={},
            families={},
            clans={},
            tribes={},
            effective_clan_tribes={},
            agent_tribes=load_raw_agent_tribes(
                agent_tribes_path,
                legacy_path=legacy_agent_tags_path,
            ),
            artifacts={},
            artifacts_by_dir={},
        )

    @classmethod
    def build(
        cls,
        project_name: str,
        *,
        projects_root: Path | str | None = None,
        agent_tribes_path: Path | str | None = None,
        legacy_agent_tags_path: Path | str | None = None,
    ) -> WaitDependencyIndex:
        index = cls.empty(
            agent_tribes_path=agent_tribes_path,
            legacy_agent_tags_path=legacy_agent_tags_path,
        )
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
        parent_timestamp = (
            meta.get("parent_timestamp")
            if isinstance(meta.get("parent_timestamp"), str)
            else None
        )
        clan_name = meta.get("agent_clan")
        if not isinstance(clan_name, str) or not clan_name:
            legacy_family = meta.get("agent_family")
            if (
                meta.get("agent_family_parallel") is True
                and isinstance(legacy_family, str)
                and legacy_family
            ):
                clan_name = legacy_family
        if not isinstance(clan_name, str) or not clan_name:
            clan_name = None
        generation: str | None = None
        if clan_name is not None:
            generation_value = meta.get("agent_clan_generation")
            generation = (
                generation_value
                if isinstance(generation_value, str) and generation_value
                else parent_timestamp or timestamp
            )
        clan_tribe = self._valid_tribe(meta.get("clan_tribe"))
        artifact = ArtifactCandidate(
            name=name if isinstance(name, str) else str(workflow_name or ""),
            timestamp=timestamp,
            project_name=project_name,
            artifact_dir=str(artifact_dir),
            parent_timestamp=parent_timestamp,
            family_name=family_name,
            is_resolved=is_resolved,
            is_done=is_done,
            is_identity_success=is_identity_success,
            is_failed=is_failed,
            is_queued=is_queued,
            clan_name=clan_name,
            clan_generation=generation,
            clan_tribe=clan_tribe,
        )
        if project_name:
            self.artifacts[(project_name, timestamp)] = artifact
        self.artifacts_by_dir[str(artifact_dir)] = artifact

        if isinstance(workflow_name, str):
            self.workflows.setdefault(workflow_name, []).append(artifact)
            if family_name is not None:
                self.families.setdefault(family_name, []).append(artifact)

        if clan_name is not None and generation is not None:
            self.clans.setdefault(clan_name, {}).setdefault(generation, []).append(
                artifact
            )
            self._refresh_effective_clan_tribe(clan_name, generation)

        canonical_meta = canonicalize_agent_tribe_metadata(dict(meta))
        direct_tribes = {
            tribe
            for tribe in (
                self._valid_tribe(canonical_meta.get("tribe")),
                self._posthoc_tribe(meta, timestamp),
            )
            if tribe is not None
        }
        for tribe in direct_tribes:
            self.tribes.setdefault(tribe, []).append(artifact)

    @staticmethod
    def _valid_tribe(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            return validate_tribe_name(value)
        except InvalidTribeError:
            return None

    def _posthoc_tribe(self, meta: Mapping[str, Any], timestamp: str) -> str | None:
        cl_name = meta.get("cl_name")
        if not isinstance(cl_name, str) or not cl_name:
            return None
        for agent_type in ("workflow", "run"):
            tribe = self.agent_tribes.get((agent_type, cl_name, timestamp))
            if tribe is not None:
                return tribe
        return None

    def _refresh_effective_clan_tribe(
        self,
        clan_name: str,
        generation: str,
    ) -> None:
        members = self.clans[clan_name][generation]
        resolution = resolve_clan_tribe(
            clan_name,
            generation,
            [
                ClanTribeMemberWire(
                    agent_clan=clan_name,
                    agent_clan_generation=generation,
                    launch_timestamp=member.timestamp,
                    identity=member.artifact_dir,
                    clan_tribe=member.clan_tribe,
                )
                for member in members
            ],
        )
        key = (clan_name, generation)
        if resolution.tribe is None:
            self.effective_clan_tribes.pop(key, None)
        else:
            self.effective_clan_tribes[key] = resolution.tribe

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


def build_wait_dependency_index(
    project_name: str,
    *,
    projects_root: Path | str | None = None,
    agent_tribes_path: Path | str | None = None,
    legacy_agent_tags_path: Path | str | None = None,
) -> WaitDependencyIndex:
    return WaitDependencyIndex.build(
        project_name,
        projects_root=projects_root,
        agent_tribes_path=agent_tribes_path,
        legacy_agent_tags_path=legacy_agent_tags_path,
    )
