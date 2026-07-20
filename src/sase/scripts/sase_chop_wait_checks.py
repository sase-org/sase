#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    dependency_resolution_status,
    read_json_dict as _read_json_dict,
)


@dataclass(frozen=True)
class _WaitingMarker:
    ready_path: Path
    waiting_path: Path


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
                    ready_path=ready_path,
                    waiting_path=waiting_path,
                )
            )

    dependency_index.add_many(artifact_rows)

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
        resolved_deps = data.get("resolved_deps", [])
        if not isinstance(wait_for_artifacts, list):
            wait_for_artifacts = []
        if not isinstance(resolved_deps, list):
            resolved_deps = []
        if not isinstance(waiting_for, list) or (
            not waiting_for and not wait_for_artifacts
        ):
            skipped_invalid += 1
            continue

        status = dependency_resolution_status(
            dependency_index,
            waiting_for,
            wait_for_artifacts,
            resolved_deps,
            self_artifact_dir=waiting_marker.waiting_path.parent,
        )
        if status.resolved:
            cl_name = data.get("cl_name", "unknown")
            runtime.log(
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
        },
        reason=reason,
    )


def main() -> None:
    run_builtin_chop("wait_checks")


if __name__ == "__main__":
    main()
