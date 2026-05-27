#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe.chop_script_context import read_chop_context
from sase.core.paths import sase_projects_dir
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    agent_family_base,
    is_plan_chain_artifact_meta,
)

_SUCCESS_OUTCOME = "completed"


@dataclass(frozen=True)
class _WaitCandidate:
    timestamp: str
    is_resolved: bool


@dataclass(frozen=True)
class _ArtifactCandidate:
    name: str
    timestamp: str
    outcome: str | None
    parent_timestamp: str | None


@dataclass(frozen=True)
class _FamilyCandidate:
    timestamp: str
    is_resolved: bool


@dataclass
class _WaitDependencyIndex:
    named: dict[str, _WaitCandidate]
    workflows: dict[str, list[_ArtifactCandidate]]
    families: dict[str, list[_ArtifactCandidate]]

    @classmethod
    def empty(cls) -> "_WaitDependencyIndex":
        return cls(named={}, workflows={}, families={})

    def add(self, artifact_dir: Path, meta: dict[str, Any]) -> None:
        outcome = _done_outcome(artifact_dir)
        timestamp = artifact_dir.name

        name = meta.get("name")
        if isinstance(name, str):
            candidate = _WaitCandidate(
                timestamp=timestamp,
                is_resolved=outcome == _SUCCESS_OUTCOME,
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
                outcome=outcome,
                parent_timestamp=parent_timestamp,
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
                is_resolved=all(
                    candidate.outcome == _SUCCESS_OUTCOME for candidate in generation
                ),
            )

        # Legacy recovery path: if only child artifacts remain, judge the known
        # generation by all retained family members.
        newest_timestamp = max(candidate.timestamp for candidate in family_agents)
        return _FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=all(
                candidate.outcome == _SUCCESS_OUTCOME for candidate in family_agents
            ),
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
                is_resolved=latest.outcome == _SUCCESS_OUTCOME,
            )

        root = max(roots, key=lambda candidate: candidate.timestamp)
        if root.outcome != _SUCCESS_OUTCOME:
            return _WaitCandidate(timestamp=root.timestamp, is_resolved=False)

        for child in workflow_agents:
            if child.parent_timestamp == root.timestamp and (
                child.outcome != _SUCCESS_OUTCOME
            ):
                return _WaitCandidate(timestamp=root.timestamp, is_resolved=False)

        return _WaitCandidate(timestamp=root.timestamp, is_resolved=True)

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
        return latest.is_resolved


@dataclass(frozen=True)
class _WaitingMarker:
    ready_path: Path
    waiting_path: Path


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _done_outcome(artifact_dir: Path) -> str | None:
    done_data = _read_json_dict(artifact_dir / "done.json")
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    read_chop_context(args.context)  # validate context file

    def log(message: str, style: str | None = None) -> None:
        print(message)

    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        log(
            "wait_checks: projects=0 artifacts=0 waiting=0 ready_written=0 reason=no_projects_dir"
        )
        return

    projects = 0
    artifacts = 0
    waiting_markers = 0
    ready_written = 0
    skipped_ready = 0
    skipped_invalid = 0
    unresolved = 0
    dependency_index = _WaitDependencyIndex.empty()
    pending_waiting_markers: list[_WaitingMarker] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        projects += 1

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue
            artifacts += 1

            meta = _read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                dependency_index.add(artifact_dir, meta)

            waiting_path = artifact_dir / "waiting.json"
            if not waiting_path.exists():
                continue
            waiting_markers += 1

            # Already resolved -- skip
            ready_path = artifact_dir / "ready.json"
            if ready_path.exists():
                skipped_ready += 1
                continue

            pending_waiting_markers.append(
                _WaitingMarker(
                    ready_path=ready_path,
                    waiting_path=waiting_path,
                )
            )

    for waiting_marker in pending_waiting_markers:
        try:
            with open(waiting_marker.waiting_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped_invalid += 1
            continue

        if not isinstance(data, dict):
            skipped_invalid += 1
            continue

        waiting_for = data.get("waiting_for", [])
        if not isinstance(waiting_for, list) or not waiting_for:
            skipped_invalid += 1
            continue

        # Check if all dependencies completed successfully.
        all_done = True
        for name in waiting_for:
            if not isinstance(name, str) or not dependency_index.is_resolved(name):
                all_done = False
                break

        if all_done:
            cl_name = data.get("cl_name", "unknown")
            log(
                f"[wait_checks] Dependencies satisfied for {cl_name}, "
                f"waited on: {', '.join(waiting_for)}",
            )
            try:
                with open(waiting_marker.ready_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"resolved_deps": waiting_for},
                        f,
                        indent=2,
                    )
            except OSError:
                skipped_invalid += 1
            else:
                ready_written += 1
        else:
            unresolved += 1

    summary = (
        "wait_checks: "
        f"projects={projects} artifacts={artifacts} waiting={waiting_markers} "
        f"ready_written={ready_written} already_ready={skipped_ready} "
        f"invalid={skipped_invalid} unresolved={unresolved}"
    )
    if ready_written == 0:
        if projects == 0:
            reason = "no_project_dirs"
        elif waiting_markers == 0:
            reason = "no_waiting_markers"
        elif unresolved > 0:
            reason = "dependencies_not_ready"
        elif skipped_ready > 0:
            reason = "waiting_markers_already_ready"
        else:
            reason = "no_ready_markers_written"
        summary += f" reason={reason}"
    log(summary)


if __name__ == "__main__":
    main()
