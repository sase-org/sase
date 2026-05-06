#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import argparse
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe.chop_script_context import read_chop_context

_SUCCESS_OUTCOME = "completed"


@dataclass(frozen=True)
class _WaitCandidate:
    timestamp: str
    is_resolved: bool


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


def _iter_ace_run_artifacts() -> Iterator[tuple[Path, dict[str, Any]]]:
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return

    for project_dir in project_iter:
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        try:
            artifact_iter = ace_run_dir.iterdir()
        except OSError:
            continue

        for artifact_dir in artifact_iter:
            if not artifact_dir.is_dir():
                continue
            meta = _read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                yield artifact_dir, meta


def _find_latest_named_dependency(name: str) -> _WaitCandidate | None:
    latest: _WaitCandidate | None = None

    for artifact_dir, meta in _iter_ace_run_artifacts():
        if meta.get("name") != name:
            continue

        outcome = _done_outcome(artifact_dir)
        if outcome is None:
            # A matching live agent, crashed no-done artifact, or dismissed
            # no-done artifact is not a successful dependency.
            is_resolved = False
        else:
            is_resolved = outcome == _SUCCESS_OUTCOME

        candidate = _WaitCandidate(
            timestamp=artifact_dir.name,
            is_resolved=is_resolved,
        )
        if latest is None or candidate.timestamp > latest.timestamp:
            latest = candidate

    return latest


def _find_latest_workflow_dependency(name: str) -> _WaitCandidate | None:
    workflow_agents = [
        (artifact_dir, meta)
        for artifact_dir, meta in _iter_ace_run_artifacts()
        if meta.get("workflow_name") == name
    ]
    if not workflow_agents:
        return None

    roots = [
        (artifact_dir, meta)
        for artifact_dir, meta in workflow_agents
        if not meta.get("parent_timestamp")
    ]
    if not roots:
        # Some older/renamed runs may only retain workflow_name on child
        # artifacts. Preserve the recovery path by judging the newest such
        # artifact, while still requiring an explicit successful done marker.
        artifact_dir, _meta = max(workflow_agents, key=lambda item: item[0].name)
        return _WaitCandidate(
            timestamp=artifact_dir.name,
            is_resolved=_done_outcome(artifact_dir) == _SUCCESS_OUTCOME,
        )

    root_dir, _root_meta = max(roots, key=lambda item: item[0].name)
    root_outcome = _done_outcome(root_dir)
    if root_outcome != _SUCCESS_OUTCOME:
        return _WaitCandidate(timestamp=root_dir.name, is_resolved=False)

    child_agents = [
        (artifact_dir, meta)
        for artifact_dir, meta in workflow_agents
        if meta.get("parent_timestamp") == root_dir.name
    ]
    for child_dir, _child_meta in child_agents:
        if _done_outcome(child_dir) != _SUCCESS_OUTCOME:
            return _WaitCandidate(timestamp=root_dir.name, is_resolved=False)

    return _WaitCandidate(timestamp=root_dir.name, is_resolved=True)


def _is_wait_dependency_resolved(name: str) -> bool:
    candidates = [
        candidate
        for candidate in (
            _find_latest_workflow_dependency(name),
            _find_latest_named_dependency(name),
        )
        if candidate is not None
    ]
    if not candidates:
        return False

    latest = max(candidates, key=lambda candidate: candidate.timestamp)
    return latest.is_resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    read_chop_context(args.context)  # validate context file

    def log(message: str, style: str | None = None) -> None:
        print(message)

    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            waiting_path = artifact_dir / "waiting.json"
            if not waiting_path.exists():
                continue

            # Already resolved -- skip
            ready_path = artifact_dir / "ready.json"
            if ready_path.exists():
                continue

            try:
                with open(waiting_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            waiting_for = data.get("waiting_for", [])
            if not isinstance(waiting_for, list) or not waiting_for:
                continue

            # Check if all dependencies completed successfully.
            all_done = True
            for name in waiting_for:
                if not isinstance(name, str) or not _is_wait_dependency_resolved(name):
                    all_done = False
                    break

            if all_done:
                cl_name = data.get("cl_name", "unknown")
                log(
                    f"[wait_checks] Dependencies satisfied for {cl_name}, "
                    f"waited on: {', '.join(waiting_for)}",
                )
                try:
                    with open(ready_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {"resolved_deps": waiting_for},
                            f,
                            indent=2,
                        )
                except OSError:
                    pass


if __name__ == "__main__":
    main()
