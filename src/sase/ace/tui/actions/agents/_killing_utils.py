"""Shared utilities for agent killing and dismissal."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
)
from sase.core.agent_cleanup_execution import try_delete_agent_artifacts
from sase.core.wait_dependency_resolution import read_json_dict

if TYPE_CHECKING:
    from ...models import Agent


def delete_agent_artifacts(
    artifacts_dir: str | None,
    *,
    before_delete: Callable[[str | None], None] | None = None,
) -> None:
    """Delete artifact files that cause an agent to be loaded.

    Removes workflow_state.json, done.json, and prompt_step_*.json files
    from the artifacts directory so the agent won't be reloaded on restart.

    Args:
        artifacts_dir: Path to the agent's artifacts directory, or None.
    """
    if not artifacts_dir:
        return

    if before_delete is not None:
        before_delete(artifacts_dir)

    _resolve_waiters_before_artifact_delete(artifacts_dir)

    if try_delete_agent_artifacts(artifacts_dir):
        delete_agent_artifact_index_artifacts([artifacts_dir])
        return

    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        delete_agent_artifact_index_artifacts([artifacts_dir])
        return

    # Delete files that the loaders scan for
    for pattern in ("workflow_state.json", "done.json", "prompt_step_*.json"):
        for f in artifacts_path.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass
    delete_agent_artifact_index_artifacts([artifacts_dir])


def _resolve_waiters_before_artifact_delete(artifacts_dir: str) -> None:
    artifacts_path = Path(artifacts_dir)
    meta = read_json_dict(artifacts_path / "agent_meta.json")
    deleted_name = _meta_name(meta)
    context = _artifact_project_context(artifacts_path)
    if context is None:
        return

    project_name, workflow_dir_name, projects_root, timestamp = context
    dependency_succeeded = _done_outcome(artifacts_path) == "completed"
    failed_dep = _failed_dependency_record(
        name=deleted_name,
        project_name=project_name,
        timestamp=timestamp,
        artifacts_dir=artifacts_path,
    )

    try:
        artifact_dirs = tuple(
            iter_agent_artifact_dirs(
                project_name,
                workflow_dir_name,
                projects_root=projects_root,
            )
        )
    except Exception:
        return

    for waiter_dir in artifact_dirs:
        if _same_artifact_dir(waiter_dir, artifacts_path):
            continue
        waiting_path = waiter_dir / "waiting.json"
        ready_path = waiter_dir / "ready.json"
        if not waiting_path.exists() or ready_path.exists():
            continue
        waiting_data = read_json_dict(waiting_path)
        if waiting_data is None:
            continue
        waiting_for = _string_list(waiting_data.get("waiting_for"))
        wait_for_artifacts = waiting_data.get("wait_for_artifacts")
        if not isinstance(wait_for_artifacts, list):
            wait_for_artifacts = []
        if not _waiting_marker_references_deleted_dependency(
            waiting_for=waiting_for,
            wait_for_artifacts=wait_for_artifacts,
            deleted_name=deleted_name,
            project_name=project_name,
            timestamp=timestamp,
            artifacts_dir=artifacts_path,
        ):
            continue
        if dependency_succeeded:
            ready_data: dict[str, object] = {"resolved_deps": waiting_for}
        else:
            ready_data = {
                "cancelled": True,
                "reason": "dependency_failed",
                "resolved_deps": waiting_for,
                "failed_deps": [failed_dep],
            }
        try:
            with open(ready_path, "w", encoding="utf-8") as f:
                json.dump(ready_data, f, indent=2)
        except OSError:
            continue


def _artifact_project_context(
    artifacts_path: Path,
) -> tuple[str, str, Path, str] | None:
    for parent in artifacts_path.parents:
        if parent.name != "artifacts":
            continue
        project_dir = parent.parent
        try:
            relative = artifacts_path.relative_to(parent)
        except ValueError:
            continue
        if len(relative.parts) < 2:
            continue
        return (
            project_dir.name,
            relative.parts[0],
            project_dir.parent,
            artifacts_path.name,
        )
    return None


def _meta_name(meta: dict[str, object] | None) -> str | None:
    if meta is None:
        return None
    name = meta.get("name")
    return name if isinstance(name, str) and name else None


def _done_outcome(artifacts_path: Path) -> str | None:
    done_data = read_json_dict(artifacts_path / "done.json")
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _waiting_marker_references_deleted_dependency(
    *,
    waiting_for: list[str],
    wait_for_artifacts: list[object],
    deleted_name: str | None,
    project_name: str,
    timestamp: str,
    artifacts_dir: Path,
) -> bool:
    if deleted_name is not None and deleted_name in waiting_for:
        return True
    return any(
        isinstance(dependency, dict)
        and _identity_dependency_matches(
            dependency,
            project_name=project_name,
            timestamp=timestamp,
            artifacts_dir=artifacts_dir,
        )
        for dependency in wait_for_artifacts
    )


def _identity_dependency_matches(
    dependency: dict[object, object],
    *,
    project_name: str,
    timestamp: str,
    artifacts_dir: Path,
) -> bool:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and _same_artifact_dir(
        artifact_dir, artifacts_dir
    ):
        return True
    return (
        dependency.get("project_name") == project_name
        and dependency.get("timestamp") == timestamp
    )


def _failed_dependency_record(
    *,
    name: str | None,
    project_name: str,
    timestamp: str,
    artifacts_dir: Path,
) -> dict[str, str]:
    record = {
        "name": name or "",
        "timestamp": timestamp,
        "project_name": project_name,
        "artifact_dir": str(artifacts_dir),
    }
    return {key: value for key, value in record.items() if value}


def _same_artifact_dir(left: str | Path, right: str | Path) -> bool:
    return _artifact_dir_key(left) == _artifact_dir_key(right)


def _artifact_dir_key(value: str | Path) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return str(value)


def dismiss_notifications_for_agents(agents: Iterable[Agent]) -> int:
    """Dismiss notifications that reference any of the given agents.

    Returns the number of notifications newly marked dismissed. The notification
    store is updated atomically by the Rust-backed notification API.
    """
    from sase.notifications import dismiss_notifications_matching_agents

    return dismiss_notifications_matching_agents(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix} for agent in agents]
    )


def find_workflow_workspace_from_running_field(
    project_file: str,
    workflow_name: str,
    cl_name: str | None = None,
) -> int | None:
    """Find workspace_num for a workflow from the RUNNING field.

    Args:
        project_file: Path to the project file.
        workflow_name: The workflow name (without "workflow()" wrapper).
        cl_name: Optional CL name for more specific matching.

    Returns:
        The workspace_num if found, None otherwise.
    """
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(project_file)
    expected_workflow = f"workflow({workflow_name})"

    for claim in claims:
        if claim.workflow == expected_workflow:
            if cl_name is not None and claim.cl_name != cl_name:
                continue
            return claim.workspace_num

    return None
