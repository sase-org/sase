"""Shared wait-dependency resolution helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    canonical_plan_chain_suffix,
    is_plan_chain_artifact_meta,
    planner_row_name,
)

_SUCCESS_OUTCOME = "completed"
_IDENTITY_SUCCESS_OUTCOMES = frozenset({"completed", "plan_rejected"})
_FAILURE_OUTCOMES = frozenset({"failed", "killed", "stopped"})
_HANDOFF_TERMINAL_STEP_STATUSES = frozenset({"completed", "skipped"})


@dataclass(frozen=True)
class _WaitCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool
    is_failed: bool = False
    name: str = ""
    project_name: str = ""
    artifact_dir: str = ""


@dataclass(frozen=True)
class _ArtifactCandidate:
    name: str
    timestamp: str
    project_name: str
    artifact_dir: str
    parent_timestamp: str | None
    family_name: str | None
    is_resolved: bool
    is_done: bool
    is_identity_success: bool
    is_failed: bool = False


@dataclass(frozen=True)
class _FamilyCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool
    is_identity_success: bool = False
    is_failed: bool = False


@dataclass(frozen=True)
class _WaitDependencyStatus:
    state: str
    failed_dependencies: tuple[dict[str, str], ...] = ()

    @property
    def resolved(self) -> bool:
        return self.state == "resolved"

    @property
    def failed(self) -> bool:
        return self.state == "failed"


@dataclass(frozen=True)
class _SubmittedPlanArtifact:
    """A planner-phase artifact whose plan is submitted and awaiting review.

    ``plan_path`` is the proposed plan file. ``planner_row_name`` is the
    canonical ``<base>--plan`` row name the TUI shows for this artifact, used
    both as the ``%wait`` alias and the cross-agent ``agents[...]`` Jinja key.
    """

    plan_path: str
    planner_row_name: str
    base_name: str


def submitted_plan_artifact(
    *,
    meta: Mapping[str, Any],
    plan_path_marker: str | None,
    outcome: str | None,
) -> _SubmittedPlanArtifact | None:
    """Classify a planner artifact as submitted-and-awaiting-review.

    Mirrors the meaning of the TUI ``PLAN`` status without importing TUI
    enrichment code: a ``--plan`` role row carrying a ``plan_submitted_at``
    marker that has not been superseded by approval, replan feedback, or a
    terminal ``done.json`` outcome, plus a usable plan path. Returns ``None``
    for anything else.
    """
    if outcome is not None:
        # A terminal outcome (approved/committed/rejected/killed) means the
        # plan flow has concluded; ordinary resolution applies instead.
        return None
    if canonical_plan_chain_suffix(meta.get("role_suffix")) != PLAN_CHAIN_PLAN_SUFFIX:
        return None
    if not _has_submission_marker(meta.get("plan_submitted_at")):
        return None
    if meta.get("plan_approved"):
        return None
    if _has_submission_marker(meta.get("feedback_submitted_at")):
        return None

    plan_path = _first_nonempty_str(plan_path_marker, meta.get("plan_path"))
    if plan_path is None:
        return None

    name = meta.get("name")
    if not isinstance(name, str) or not name:
        return None
    base = agent_family_base(name) or name
    try:
        row_name = agent_family_phase_name(base, PLAN_CHAIN_PLAN_SUFFIX)
    except ValueError:
        return None
    return _SubmittedPlanArtifact(
        plan_path=plan_path,
        planner_row_name=row_name,
        base_name=base,
    )


def submitted_plan_artifact_for_dir(
    artifact_dir: Path | str,
) -> _SubmittedPlanArtifact | None:
    """Read an artifact dir and classify it as a submitted planner row."""
    artifact_path = Path(artifact_dir)
    meta = read_json_dict(artifact_path / "agent_meta.json")
    if meta is None:
        return None
    return submitted_plan_artifact(
        meta=meta,
        plan_path_marker=_plan_path_marker(artifact_path),
        outcome=_done_outcome(artifact_path),
    )


def _plan_path_marker(artifact_dir: Path) -> str | None:
    data = read_json_dict(artifact_dir / "plan_path.json")
    if data is None:
        return None
    plan_path = data.get("plan_path")
    return plan_path if isinstance(plan_path, str) and plan_path else None


def _has_submission_marker(raw_value: object) -> bool:
    """Mirror the TUI's plan-submission marker check without importing it."""
    if isinstance(raw_value, str):
        return bool(raw_value)
    if isinstance(raw_value, list):
        return any(isinstance(value, str) and value for value in raw_value)
    return False


def _first_nonempty_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


@dataclass
class WaitDependencyIndex:
    named: dict[str, _WaitCandidate]
    workflows: dict[str, list[_ArtifactCandidate]]
    families: dict[str, list[_ArtifactCandidate]]
    artifacts: dict[tuple[str, str], _ArtifactCandidate]
    artifacts_by_dir: dict[str, _ArtifactCandidate]

    @classmethod
    def empty(cls) -> WaitDependencyIndex:
        return cls(
            named={},
            workflows={},
            families={},
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
        done_data = read_json_dict(artifact_dir / "done.json")
        outcome = _done_outcome_from_data(done_data)
        is_resolved = _artifact_is_resolved(artifact_dir, meta, outcome)
        is_done = outcome == _SUCCESS_OUTCOME
        is_identity_success = _artifact_succeeded_for_identity(done_data)
        is_failed = _artifact_failed_for_identity(done_data)
        timestamp = artifact_dir.name

        name = meta.get("name")
        if isinstance(name, str):
            self._record_named_candidate(
                name,
                _WaitCandidate(
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
            plan_path_marker=_plan_path_marker(artifact_dir),
            outcome=outcome,
        )
        if plan_artifact is not None:
            self._record_named_candidate(
                plan_artifact.planner_row_name,
                _WaitCandidate(timestamp=timestamp, is_resolved=True, is_done=True),
                prefer_on_tie=True,
            )

        workflow_name = meta.get("workflow_name")
        family_name = _family_base_from_meta(meta)
        artifact = _ArtifactCandidate(
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
        )
        if project_name:
            self.artifacts[(project_name, timestamp)] = artifact
        self.artifacts_by_dir[str(artifact_dir)] = artifact

        if isinstance(workflow_name, str):
            self.workflows.setdefault(workflow_name, []).append(artifact)
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
                is_identity_success=any(
                    candidate.is_identity_success for candidate in generation
                ),
                is_failed=any(candidate.is_failed for candidate in generation),
            )

        # Legacy recovery path: if only child artifacts remain, judge the known
        # generation by all retained family members.
        newest_timestamp = max(candidate.timestamp for candidate in family_agents)
        return _FamilyCandidate(
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
        root: _ArtifactCandidate,
    ) -> _FamilyCandidate | None:
        if root.parent_timestamp:
            return None
        family_name = root.family_name or root.name
        if not family_name:
            return None
        family_agents = self.families.get(family_name)
        if not family_agents:
            return None
        generation = [
            candidate
            for candidate in family_agents
            if candidate.timestamp == root.timestamp
            or candidate.parent_timestamp == root.timestamp
        ]
        if not generation:
            return None
        newest_timestamp = max(candidate.timestamp for candidate in generation)
        return _FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=all(candidate.is_resolved for candidate in generation),
            is_done=any(candidate.is_done for candidate in generation),
            is_identity_success=any(
                candidate.is_identity_success for candidate in generation
            ),
            is_failed=any(candidate.is_failed for candidate in generation),
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

    def _record_named_candidate(
        self,
        name: str,
        candidate: _WaitCandidate,
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

    def _planner_row_candidate(self, name: str) -> _WaitCandidate | None:
        """Return a submitted-planner-row candidate for a legacy-spelled wait.

        A ``%wait`` on a legacy planner-row spelling (``base.plan``) resolves to
        the canonical ``base--plan`` named candidate. Canonical names already
        hit ``self.named`` directly, so they are skipped here.
        """
        alias = planner_row_name(name, include_legacy_dash=True)
        if alias is None or alias == name:
            return None
        return self.named.get(alias)

    def is_resolved(self, name: str) -> bool:
        candidates = [
            candidate
            for candidate in (
                self.family_candidate(name),
                self.workflow_candidate(name),
                self.named.get(name),
                self._planner_row_candidate(name),
            )
            if candidate is not None
        ]
        if not candidates:
            return False

        latest = max(candidates, key=lambda candidate: candidate.timestamp)
        return latest.is_resolved and latest.is_done

    def identity_status(
        self,
        dependency: Mapping[str, Any],
    ) -> _WaitDependencyStatus:
        candidate = self._identity_candidate(dependency)
        if candidate is None:
            return _WaitDependencyStatus("waiting")

        family_candidate = self.family_candidate_for_root(candidate)
        if family_candidate is not None:
            if family_candidate.is_failed:
                return _WaitDependencyStatus(
                    "failed",
                    (_failed_dependency_record(dependency, candidate),),
                )
            if family_candidate.is_resolved and family_candidate.is_identity_success:
                return _WaitDependencyStatus("resolved")
            return _WaitDependencyStatus("waiting")

        if candidate.is_failed:
            return _WaitDependencyStatus(
                "failed",
                (_failed_dependency_record(dependency, candidate),),
            )
        if candidate.is_identity_success:
            return _WaitDependencyStatus("resolved")
        return _WaitDependencyStatus("waiting")

    def _identity_candidate(
        self,
        dependency: Mapping[str, Any],
    ) -> _ArtifactCandidate | None:
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


def dependency_resolution_status(
    index: WaitDependencyIndex,
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object] = (),
) -> _WaitDependencyStatus:
    failed: list[dict[str, str]] = []
    identity_names: set[str] = set()
    for dependency in wait_identity_deps:
        if not isinstance(dependency, Mapping):
            return _WaitDependencyStatus("waiting")
        dependency_name = dependency.get("name")
        if isinstance(dependency_name, str) and dependency_name:
            identity_names.add(dependency_name)
        status = index.identity_status(dependency)
        if status.failed:
            failed.extend(status.failed_dependencies)
        elif not status.resolved:
            return _WaitDependencyStatus("waiting")
    if failed:
        return _WaitDependencyStatus("failed", tuple(failed))

    for name in wait_names:
        if not isinstance(name, str):
            return _WaitDependencyStatus("waiting")
        if name in identity_names:
            continue
        if not index.is_resolved(name):
            return _WaitDependencyStatus("waiting")
    return _WaitDependencyStatus("resolved")


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _done_outcome(artifact_dir: Path) -> str | None:
    done_data = read_json_dict(artifact_dir / "done.json")
    return _done_outcome_from_data(done_data)


def _done_outcome_from_data(done_data: Mapping[str, Any] | None) -> str | None:
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _artifact_failed_for_identity(done_data: Mapping[str, Any] | None) -> bool:
    if done_data is None:
        return False
    if bool(done_data.get("repeat_stopped")):
        return True
    outcome = _done_outcome_from_data(done_data)
    return outcome in _FAILURE_OUTCOMES


def _artifact_succeeded_for_identity(done_data: Mapping[str, Any] | None) -> bool:
    if done_data is None or bool(done_data.get("repeat_stopped")):
        return False
    outcome = _done_outcome_from_data(done_data)
    return outcome in _IDENTITY_SUCCESS_OUTCOMES


def _failed_dependency_record(
    dependency: Mapping[str, Any],
    candidate: _ArtifactCandidate,
) -> dict[str, str]:
    record = {
        "name": _first_nonempty_str(dependency.get("name"), candidate.name) or "",
        "timestamp": candidate.timestamp,
        "project_name": candidate.project_name,
        "artifact_dir": candidate.artifact_dir,
    }
    return {key: value for key, value in record.items() if value}


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
    "dependency_resolution_status",
    "read_json_dict",
    "submitted_plan_artifact",
    "submitted_plan_artifact_for_dir",
]
