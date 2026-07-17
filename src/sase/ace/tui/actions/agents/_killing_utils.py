"""Shared utilities for agent killing and dismissal."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
    delete_agent_artifact_index_artifacts_bounded,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_cleanup_execution import try_delete_agent_artifacts
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    dependency_resolution_status,
    read_json_dict,
)

if TYPE_CHECKING:
    from ...models import Agent


def delete_agent_artifacts(
    artifacts_dir: str | None,
    *,
    before_delete: Callable[[str | None], None] | None = None,
    artifact_index_timeout_seconds: float | None = None,
) -> bool:
    """Delete artifact files that cause an agent to be loaded.

    Removes workflow_state.json, done.json, and prompt_step_*.json files
    from the artifacts directory so the agent won't be reloaded on restart.

    Args:
        artifacts_dir: Path to the agent's artifacts directory, or None.
    """
    if not artifacts_dir:
        return True

    if before_delete is not None:
        before_delete(artifacts_dir)

    _resolve_waiters_before_artifact_delete(artifacts_dir)

    deleted = try_delete_agent_artifacts(artifacts_dir)
    artifacts_path = Path(artifacts_dir)
    if not deleted and artifacts_path.is_dir():
        # Delete files that the loaders scan for.
        for pattern in ("workflow_state.json", "done.json", "prompt_step_*.json"):
            for f in artifacts_path.glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

    if artifact_index_timeout_seconds is None:
        delete_agent_artifact_index_artifacts([artifacts_dir])
        return True
    return delete_agent_artifact_index_artifacts_bounded(
        [artifacts_dir],
        timeout_seconds=artifact_index_timeout_seconds,
    )


def _resolve_waiters_before_artifact_delete(artifacts_dir: str) -> None:
    artifacts_path = Path(artifacts_dir)
    meta = read_json_dict(artifacts_path / "agent_meta.json")
    deleted_name = _meta_name(meta)
    context = _artifact_project_context(artifacts_path)
    if context is None:
        return

    project_name, workflow_dir_name, projects_root, timestamp = context
    name_succeeded, identity_succeeded = _dependency_successes(artifacts_path)

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

    dependency_index = None
    if name_succeeded or identity_succeeded:
        try:
            dependency_index = build_wait_dependency_index(
                project_name,
                projects_root=projects_root,
            )
        except Exception:
            dependency_index = None

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
        if not name_succeeded and not identity_succeeded:
            continue
        resolved_deps = waiting_data.get("resolved_deps")
        if not isinstance(resolved_deps, list):
            resolved_deps = []
        ready_data = _ready_data_for_completed_dependency(
            dependency_index,
            waiting_for=waiting_for,
            wait_for_artifacts=wait_for_artifacts,
            resolved_deps=resolved_deps,
            waiter_dir=waiter_dir,
        )
        if ready_data is None:
            merged_resolved_deps = _memoize_completed_dependency(
                resolved_deps,
                waiting_for=waiting_for,
                wait_for_artifacts=wait_for_artifacts,
                deleted_name=deleted_name,
                project_name=project_name,
                timestamp=timestamp,
                artifacts_dir=artifacts_path,
                memoize_name=name_succeeded,
                memoize_identity=identity_succeeded,
            )
            if merged_resolved_deps == resolved_deps:
                continue
            waiting_data["resolved_deps"] = merged_resolved_deps
            try:
                with open(waiting_path, "w", encoding="utf-8") as f:
                    json.dump(waiting_data, f, indent=2)
                update_agent_artifact_index_for_marker_mutation(waiter_dir)
            except OSError:
                continue
            continue
        try:
            with open(ready_path, "w", encoding="utf-8") as f:
                json.dump(ready_data, f, indent=2)
        except OSError:
            continue


def _ready_data_for_completed_dependency(
    dependency_index: WaitDependencyIndex | None,
    *,
    waiting_for: list[str],
    wait_for_artifacts: list[object],
    resolved_deps: list[object],
    waiter_dir: Path,
) -> dict[str, object] | None:
    """Return ready marker data only when all waiter dependencies are satisfied."""
    if dependency_index is None:
        return None
    status = dependency_resolution_status(
        dependency_index,
        waiting_for,
        wait_for_artifacts,
        resolved_deps,
        self_artifact_dir=waiter_dir,
    )
    if not status.resolved:
        return None
    return {"resolved_deps": waiting_for}


def _memoize_completed_dependency(
    resolved_deps: list[object],
    *,
    waiting_for: list[str],
    wait_for_artifacts: list[object],
    deleted_name: str | None,
    project_name: str,
    timestamp: str,
    artifacts_dir: Path,
    memoize_name: bool,
    memoize_identity: bool,
) -> list[object]:
    merged = list(resolved_deps)
    if memoize_name and deleted_name is not None and deleted_name in waiting_for:
        if deleted_name not in merged:
            merged.append(deleted_name)

    if not memoize_identity:
        return merged

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, dict) or not _identity_dependency_matches(
            dependency,
            project_name=project_name,
            timestamp=timestamp,
            artifacts_dir=artifacts_dir,
        ):
            continue
        memo = {
            key: value
            for key in ("name", "project_name", "timestamp", "artifact_dir")
            if isinstance((value := dependency.get(key)), str) and value
        }
        if memo and not any(
            isinstance(existing, dict)
            and _identity_dependency_matches(
                existing,
                project_name=project_name,
                timestamp=timestamp,
                artifacts_dir=artifacts_dir,
            )
            for existing in merged
        ):
            merged.append(memo)
    return merged


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


def _dependency_successes(artifacts_path: Path) -> tuple[bool, bool]:
    done_data = read_json_dict(artifacts_path / "done.json")
    if done_data is None:
        return False, False
    outcome = done_data.get("outcome")
    name_succeeded = outcome == "completed"
    identity_succeeded = outcome in {"completed", "plan_rejected"} and not bool(
        done_data.get("repeat_stopped")
    )
    return name_succeeded, identity_succeeded


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
        cl_name: Optional ChangeSpec name for more specific matching.

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
