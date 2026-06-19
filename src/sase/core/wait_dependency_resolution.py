"""Shared wait-dependency resolution helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    agent_family_base,
    is_plan_chain_artifact_meta,
)

_SUCCESS_OUTCOME = "completed"
_HANDOFF_TERMINAL_STEP_STATUSES = frozenset({"completed", "skipped"})


@dataclass(frozen=True)
class _WaitCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool


@dataclass(frozen=True)
class _ArtifactCandidate:
    name: str
    timestamp: str
    parent_timestamp: str | None
    is_resolved: bool
    is_done: bool


@dataclass(frozen=True)
class _FamilyCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool


@dataclass
class WaitDependencyIndex:
    named: dict[str, _WaitCandidate]
    workflows: dict[str, list[_ArtifactCandidate]]
    families: dict[str, list[_ArtifactCandidate]]

    @classmethod
    def empty(cls) -> WaitDependencyIndex:
        return cls(named={}, workflows={}, families={})

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
                index.add(artifact_dir, meta)
        return index

    def add(self, artifact_dir: Path, meta: dict[str, Any]) -> None:
        outcome = _done_outcome(artifact_dir)
        is_resolved = _artifact_is_resolved(artifact_dir, meta, outcome)
        is_done = outcome == _SUCCESS_OUTCOME
        timestamp = artifact_dir.name

        name = meta.get("name")
        if isinstance(name, str):
            candidate = _WaitCandidate(
                timestamp=timestamp,
                is_resolved=is_resolved,
                is_done=is_done,
            )
            latest = self.named.get(name)
            if latest is None or candidate.timestamp > latest.timestamp:
                self.named[name] = candidate

        workflow_name = meta.get("workflow_name")
        if isinstance(workflow_name, str):
            parent_value = meta.get("parent_timestamp")
            parent_timestamp = parent_value if isinstance(parent_value, str) else None
            artifact = _ArtifactCandidate(
                name=name if isinstance(name, str) else workflow_name,
                timestamp=timestamp,
                parent_timestamp=parent_timestamp,
                is_resolved=is_resolved,
                is_done=is_done,
            )
            self.workflows.setdefault(workflow_name, []).append(artifact)
            family_name = _family_base_from_meta(meta)
            if family_name is not None:
                self.families.setdefault(family_name, []).append(artifact)

    def family_candidate(self, name: str) -> _FamilyCandidate | None:
        family_agents = self.families.get(name)
        if not family_agents:
            return None

        roots = [
            candidate for candidate in family_agents if not candidate.parent_timestamp
        ]
        if roots:
            root = max(roots, key=lambda candidate: candidate.timestamp)
            generation = [
                candidate
                for candidate in family_agents
                if candidate.timestamp == root.timestamp
                or candidate.parent_timestamp == root.timestamp
            ]
            newest_timestamp = max(
                (candidate.timestamp for candidate in generation),
                default=root.timestamp,
            )
            return _FamilyCandidate(
                timestamp=newest_timestamp,
                is_resolved=all(candidate.is_resolved for candidate in generation),
                is_done=any(candidate.is_done for candidate in generation),
            )

        # Legacy recovery path: if only child artifacts remain, judge the known
        # generation by all retained family members.
        newest_timestamp = max(candidate.timestamp for candidate in family_agents)
        return _FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=all(candidate.is_resolved for candidate in family_agents),
            is_done=any(candidate.is_done for candidate in family_agents),
        )

    def workflow_candidate(self, name: str) -> _WaitCandidate | None:
        workflow_agents = self.workflows.get(name)
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
            return _WaitCandidate(
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
        return _WaitCandidate(
            timestamp=root.timestamp,
            is_resolved=all(candidate.is_resolved for candidate in generation),
            is_done=any(candidate.is_done for candidate in generation),
        )

    def is_resolved(self, name: str) -> bool:
        candidates = [
            candidate
            for candidate in (
                self.family_candidate(name),
                self.workflow_candidate(name),
                self.named.get(name),
            )
            if candidate is not None
        ]
        if not candidates:
            return False

        latest = max(candidates, key=lambda candidate: candidate.timestamp)
        return latest.is_resolved and latest.is_done


def build_wait_dependency_index(
    project_name: str,
    *,
    projects_root: Path | str | None = None,
) -> WaitDependencyIndex:
    return WaitDependencyIndex.build(project_name, projects_root=projects_root)


def dependencies_resolved(
    index: WaitDependencyIndex,
    wait_names: Iterable[object],
) -> bool:
    for name in wait_names:
        if not isinstance(name, str) or not index.is_resolved(name):
            return False
    return True


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _done_outcome(artifact_dir: Path) -> str | None:
    done_data = read_json_dict(artifact_dir / "done.json")
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _artifact_is_resolved(
    artifact_dir: Path,
    meta: dict[str, Any],
    outcome: str | None,
) -> bool:
    if outcome is not None:
        return outcome == _SUCCESS_OUTCOME
    if not is_plan_chain_artifact_meta(meta):
        return False
    return _completed_handoff_workflow_state(artifact_dir)


def _completed_handoff_workflow_state(artifact_dir: Path) -> bool:
    state_data = read_json_dict(artifact_dir / "workflow_state.json")
    if state_data is None or state_data.get("status") != _SUCCESS_OUTCOME:
        return False
    if _has_failure_fields(state_data):
        return False

    steps_data = state_data.get("steps", [])
    if not isinstance(steps_data, list):
        return False

    for step_data in steps_data:
        if not isinstance(step_data, dict):
            return False
        if step_data.get("status") not in _HANDOFF_TERMINAL_STEP_STATUSES:
            return False
        if _has_failure_fields(step_data):
            return False

    return not _has_blocking_prompt_step_marker(artifact_dir)


def _has_failure_fields(data: dict[str, Any]) -> bool:
    return bool(data.get("error") or data.get("traceback"))


def _has_blocking_prompt_step_marker(artifact_dir: Path) -> bool:
    for marker_path in artifact_dir.glob("prompt_step_*.json"):
        marker_data = read_json_dict(marker_path)
        if marker_data is None:
            return True
        if marker_data.get("status") not in _HANDOFF_TERMINAL_STEP_STATUSES:
            return True
        if _has_failure_fields(marker_data):
            return True
    return False


def _family_base_from_meta(meta: dict[str, Any]) -> str | None:
    family = meta.get(AGENT_FAMILY_FIELD)
    if isinstance(family, str) and family:
        return family

    workflow_name = meta.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return None

    if is_plan_chain_artifact_meta(meta):
        return workflow_name

    name = meta.get("name")
    if isinstance(name, str) and agent_family_base(name) == workflow_name:
        return workflow_name

    return None


__all__ = [
    "WaitDependencyIndex",
    "build_wait_dependency_index",
    "dependencies_resolved",
    "read_json_dict",
]
