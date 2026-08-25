#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import json
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.bead.store_locator import closed_bead_ids_for_project
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir
from sase.core.wait_dependency_resolution import (
    KNOWN_DONE_OUTCOMES,
    WaitDependencyIndex,
    dependency_resolution_status,
    read_json_dict as _read_json_dict,
)
from sase.core.wait_dependency_resolution._types import ArtifactCandidate

_MAX_TERMINAL_BLOCKER_LOGS = 10


@dataclass(frozen=True)
class _WaitingMarker:
    project_name: str
    ready_path: Path
    waiting_path: Path


@dataclass(frozen=True)
class _TerminalBlocker:
    dependency: str
    artifact_dir: str
    outcome: str


@builtin_chop("wait_checks")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return runtime.emit_summary(
            {
                "projects": 0,
                "artifacts": 0,
                "waiting": 0,
                "ready_written": 0,
            },
            reason="no_projects_dir",
        )

    projects = 0
    artifacts = 0
    waiting_markers = 0
    ready_written = 0
    skipped_ready = 0
    skipped_invalid = 0
    unresolved = 0
    unknown_outcome = 0
    terminal_blocker_logs = 0
    terminal_blocker_suppressed = 0
    dependency_index = WaitDependencyIndex.empty()
    pending_waiting_markers: list[_WaitingMarker] = []
    artifact_rows: list[tuple[Path, dict[str, Any], str]] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        projects += 1

        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            artifacts += 1

            meta = _read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                artifact_rows.append((artifact_dir, meta, project_dir.name))

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
                    project_name=project_dir.name,
                    ready_path=ready_path,
                    waiting_path=waiting_path,
                )
            )

    dependency_index.add_many(artifact_rows)

    closed_bead_ids_by_project: dict[str, frozenset[str] | None] = {}
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
        wait_for_artifacts = data.get("wait_for_artifacts", [])
        wait_for_fork_sources = data.get("wait_for_fork_sources", [])
        wait_for_beads = data.get("wait_for_beads", [])
        resolved_deps = data.get("resolved_deps", [])
        if not isinstance(wait_for_artifacts, list):
            wait_for_artifacts = []
        if not isinstance(wait_for_fork_sources, list):
            wait_for_fork_sources = []
        if not isinstance(wait_for_beads, list):
            wait_for_beads = []
        if not isinstance(resolved_deps, list):
            resolved_deps = []
        if not isinstance(waiting_for, list) or (
            not waiting_for
            and not wait_for_artifacts
            and not wait_for_fork_sources
            and not wait_for_beads
        ):
            skipped_invalid += 1
            continue

        closed_bead_ids = None
        if wait_for_beads:
            project_name = waiting_marker.project_name
            if project_name not in closed_bead_ids_by_project:
                closed_bead_ids_by_project[project_name] = closed_bead_ids_for_project(
                    project_name
                )
            closed_bead_ids = closed_bead_ids_by_project[project_name]

        status = dependency_resolution_status(
            dependency_index,
            waiting_for,
            wait_for_artifacts,
            resolved_deps,
            wait_fork_sources=wait_for_fork_sources,
            wait_beads=wait_for_beads,
            closed_bead_ids=closed_bead_ids,
            self_artifact_dir=waiting_marker.waiting_path.parent,
        )
        if status.resolved:
            cl_name = data.get("cl_name", "unknown")
            waited_on = ", ".join(waiting_for)
            if wait_for_beads:
                bead_wait = f"beads: {', '.join(wait_for_beads)}"
                waited_on = f"{waited_on}; {bead_wait}" if waited_on else bead_wait
            runtime.log(
                f"[wait_checks] Dependencies satisfied for {cl_name}, "
                f"waited on: {waited_on}",
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
            terminal_blockers = _terminal_blockers(
                dependency_index,
                waiting_for,
                wait_for_artifacts,
                status.blocked_on,
                self_artifact_dir=waiting_marker.waiting_path.parent,
            )
            for blocker in terminal_blockers:
                if blocker.outcome not in KNOWN_DONE_OUTCOMES:
                    unknown_outcome += 1
                    runtime.log(
                        "[wait_checks] Unknown done outcome blocks waiter "
                        f"{waiting_marker.waiting_path.parent}: "
                        f"dependency={blocker.dependency} "
                        f"artifact={blocker.artifact_dir} "
                        f"outcome={blocker.outcome!r}",
                    )
                if terminal_blocker_logs < _MAX_TERMINAL_BLOCKER_LOGS:
                    terminal_blocker_logs += 1
                    runtime.log(
                        "[wait_checks] Terminal dependency still blocks waiter "
                        f"{waiting_marker.waiting_path.parent}: "
                        f"dependency={blocker.dependency} "
                        f"artifact={blocker.artifact_dir} "
                        f"outcome={blocker.outcome!r}",
                    )
                else:
                    terminal_blocker_suppressed += 1

    if terminal_blocker_suppressed:
        runtime.log(
            "[wait_checks] Suppressed "
            f"{terminal_blocker_suppressed} additional terminal blocker log(s)",
        )

    reason = None
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
    return runtime.emit_summary(
        {
            "projects": projects,
            "artifacts": artifacts,
            "waiting": waiting_markers,
            "ready_written": ready_written,
            "already_ready": skipped_ready,
            "invalid": skipped_invalid,
            "unresolved": unresolved,
            "unknown_outcome": unknown_outcome,
        },
        reason=reason,
    )


def _terminal_blockers(
    dependency_index: WaitDependencyIndex,
    waiting_for: list[object],
    wait_for_artifacts: list[object],
    blocked_on: tuple[str, ...],
    *,
    self_artifact_dir: Path,
) -> tuple[_TerminalBlocker, ...]:
    blocked_labels = frozenset(blocked_on)
    blockers: list[_TerminalBlocker] = []
    identity_names: set[str] = set()

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, Mapping):
            continue
        name = dependency.get("name")
        if isinstance(name, str) and name:
            identity_names.add(name)
        label = _dependency_label(dependency)
        if label not in blocked_labels:
            continue
        candidate = _artifact_candidate_for_identity(dependency_index, dependency)
        if candidate is not None and _identity_terminal_blocker(candidate):
            outcome = candidate.outcome
            assert outcome is not None
            blockers.append(
                _TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=outcome,
                )
            )

    waiter_launch_cutoff = self_artifact_dir.name
    for name in waiting_for:
        if not isinstance(name, str) or name in identity_names:
            continue
        if name not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_name(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            assert candidate.outcome is not None
            blockers.append(
                _TerminalBlocker(
                    dependency=name,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                )
            )

    return tuple(blockers)


def _artifact_candidate_for_identity(
    dependency_index: WaitDependencyIndex,
    dependency: Mapping[str, Any],
) -> ArtifactCandidate | None:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        candidate = dependency_index.artifacts_by_dir.get(artifact_dir)
        if candidate is not None:
            return candidate

    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if isinstance(project_name, str) and isinstance(timestamp, str):
        return dependency_index.artifacts.get((project_name, timestamp))
    return None


def _identity_terminal_blocker(candidate: ArtifactCandidate) -> bool:
    return (
        candidate.has_done_marker
        and candidate.outcome is not None
        and not candidate.is_identity_success
    )


def _dependency_label(dependency: Mapping[str, Any]) -> str:
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


def main() -> None:
    run_builtin_chop("wait_checks")


if __name__ == "__main__":
    main()
