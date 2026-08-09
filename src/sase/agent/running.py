"""Running-agent lifecycle management and stable public exports.

Listing and display adaptation live in :mod:`sase.agent.running_listing`.
This module retains named-agent termination and re-exports the established
listing API for callers.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sase.agent.names import find_named_agent, is_process_alive
from sase.agent.running_listing import (
    _DONE_AGENTS_CAP_PER_PROJECT as _DONE_AGENTS_CAP_PER_PROJECT,
    RunningAgentInfo as RunningAgentInfo,
    active_status_for_record as _active_status_for_record,
    list_all_agents as list_all_agents,
    list_running_agents as list_running_agents,
)
from sase.agent.user_kill import request_user_kill
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)


@dataclass
class KillResult:
    """Result of a kill_named_agent() attempt."""

    success: bool
    message: str
    reason: str | None = None
    status: str | None = None
    pid: int | None = None
    changed: bool = False
    artifacts_dir: str | None = None
    project: str | None = None
    timestamp: str | None = None


_KillResult = KillResult


def kill_named_agent(name: str, *, exact_name: bool = False) -> _KillResult:
    """Kill a running agent by its assigned name.

    Locates the agent via find_named_agent(), derives the project context
    from its artifacts_dir, looks up the PID, sends SIGTERM to the process
    group, and cleans up the workspace claim or running marker.

    Args:
        name: The agent name to kill.
        exact_name: When true, reject workflow-name matches and only kill an
            artifact whose ``agent_meta.json`` name exactly matches ``name``.

    Returns:
        A KillResult with success status and a human-readable message.
    """
    agent = find_named_agent(name)
    if agent is None:
        return _KillResult(
            False,
            f"No agent found with name '{name}'",
            reason="not_found",
            status="not_found",
        )

    if exact_name and not _agent_meta_name_matches(agent.artifacts_dir, name):
        return _KillResult(
            False,
            f"No agent found with name '{name}'",
            reason="not_found",
            status="not_found",
        )

    if agent.is_done:
        outcome_str = f" ({agent.outcome})" if agent.outcome else ""
        return _KillResult(
            False,
            f"Agent '{name}' already completed{outcome_str}",
            reason="already_completed",
            status="already_completed",
            artifacts_dir=agent.artifacts_dir,
        )

    # Derive project context from artifacts_dir.
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    artifacts_path = Path(agent.artifacts_dir)
    path_info = parse_agent_artifact_path(artifacts_path)
    if path_info is None:
        timestamp = artifacts_path.name
        project_dir = artifacts_path.parent.parent.parent
        project_name = project_dir.name
    else:
        timestamp = path_info.timestamp
        project_name = path_info.project_name
        project_dir = artifacts_path
        while project_dir.name != project_name and project_dir.parent != project_dir:
            project_dir = project_dir.parent
    project_file = preferred_project_spec_path(str(project_dir), project_name)

    # Find PID
    pid: int | None = None
    cl_name: str | None = None
    is_home = project_name == "home"

    if is_home:
        # Home mode: read PID from running.json
        pid = _read_pid_from_running_marker(artifacts_path)
        cl_name = _read_cl_name_from_meta(artifacts_path)
    else:
        # Non-home: scan RUNNING field for matching artifacts_timestamp
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                pid = _valid_pid(claim.pid)
                cl_name = claim.cl_name
                break
        if cl_name is None:
            cl_name = _read_cl_name_from_artifacts(artifacts_path)

    if pid is None:
        meta = _read_agent_meta(artifacts_path)
        meta_pid = _valid_pid(meta.get("pid")) if meta is not None else None
        if (
            meta is not None
            and meta_pid is not None
            and is_process_alive(meta, artifacts_path)
        ):
            pid = meta_pid
            if cl_name is None:
                cl_name = _read_cl_name_from_artifacts(artifacts_path)
        else:
            if not is_home:
                _release_workspace_claim(project_file, timestamp)
            _remove_agent_state_markers(
                artifacts_path,
                remove_running=True,
                remove_waiting=True,
            )
            _record_dismissal(cl_name, timestamp)
            _dismiss_agent_notifications(cl_name, timestamp)
            return _KillResult(
                True,
                f"Agent '{name}' was not running; cleaned up stale state",
                status="not_running",
                changed=True,
                artifacts_dir=agent.artifacts_dir,
                project=project_name,
                timestamp=timestamp,
            )

    kill_result = request_user_kill(
        pid,
        artifacts_dir=artifacts_path,
        source="agents_kill",
        wait=True,
    )
    if not kill_result.success and kill_result.status == "permission_denied":
        return _KillResult(
            False,
            f"Permission denied killing agent '{name}' (PID {pid})",
            reason="permission_denied",
            status="permission_denied",
            pid=pid,
            artifacts_dir=agent.artifacts_dir,
            project=project_name,
            timestamp=timestamp,
        )
    status = kill_result.status

    # Cleanup
    if is_home:
        _remove_agent_state_markers(
            artifacts_path,
            remove_running=True,
            remove_waiting=_kill_result_confirms_dead(status),
        )
    else:
        _release_workspace_claim(project_file, timestamp)
        if _kill_result_confirms_dead(status):
            _remove_agent_state_markers(
                artifacts_path,
                remove_running=False,
                remove_waiting=True,
            )

    _record_dismissal(cl_name, timestamp)
    _dismiss_agent_notifications(cl_name, timestamp)

    return _KillResult(
        True,
        f"Killed agent '{name}' (PID {pid})",
        status=status,
        pid=pid,
        changed=True,
        artifacts_dir=agent.artifacts_dir,
        project=project_name,
        timestamp=timestamp,
    )


def _valid_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 1 else None


def _read_json_dict(path: Path) -> dict[str, object] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _read_agent_meta(artifacts_path: Path) -> dict[str, object] | None:
    return _read_json_dict(artifacts_path / "agent_meta.json")


def _read_pid_from_running_marker(artifacts_path: Path) -> int | None:
    data = _read_json_dict(artifacts_path / "running.json")
    return _valid_pid(data.get("pid")) if data is not None else None


def _read_str_field(data: dict[str, object] | None, *keys: str) -> str | None:
    if data is None:
        return None
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _read_cl_name_from_artifacts(artifacts_path: Path) -> str | None:
    meta_value = _read_str_field(
        _read_agent_meta(artifacts_path),
        "patch_name",
        "cl_name",
        "changespec_name",
    )
    if meta_value is not None:
        return meta_value

    waiting_value = _read_str_field(
        _read_json_dict(artifacts_path / "waiting.json"),
        "patch_name",
        "cl_name",
    )
    if waiting_value is not None:
        return waiting_value

    workflow_state = _read_json_dict(artifacts_path / "workflow_state.json")
    context = workflow_state.get("context") if workflow_state is not None else None
    if isinstance(context, dict):
        return _read_str_field(context, "patch_name", "cl_name")
    return None


def _release_workspace_claim(project_file: str, timestamp: str) -> None:
    from sase.running_field import get_claimed_workspaces, release_workspace

    for claim in get_claimed_workspaces(project_file):
        if claim.artifacts_timestamp == timestamp:
            release_workspace(
                project_file, claim.workspace_num, claim.workflow, claim.cl_name
            )
            break


def _kill_result_confirms_dead(status: str | None) -> bool:
    return status in {"already_stopped", "killed"}


def _remove_agent_state_markers(
    artifacts_path: Path,
    *,
    remove_running: bool,
    remove_waiting: bool,
) -> bool:
    marker_names: list[str] = []
    if remove_waiting:
        marker_names.append("waiting.json")
    if remove_running:
        marker_names.append("running.json")

    changed = False
    for marker_name in marker_names:
        try:
            (artifacts_path / marker_name).unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        else:
            changed = True

    if changed:
        try:
            update_agent_artifact_index_for_marker_mutation(artifacts_path)
        except Exception:
            pass
    return changed


def _read_cl_name_from_meta(artifacts_path: Path) -> str | None:
    return _read_str_field(_read_agent_meta(artifacts_path), "patch_name", "cl_name")


def _record_dismissal(cl_name: str | None, raw_suffix: str) -> None:
    """Add the killed agent to the persistent dismissed-agents index.

    Failure to write the index must never flip a successful kill into a
    failure — the kill itself already happened.
    """
    try:
        from sase.core.agent_types import AgentType
        from sase.core.dismissed_agents_facade import (
            load_dismissed_agents,
            persist_dismissed_agents as save_dismissed_agents,
        )

        identity = (AgentType.RUNNING, cl_name or "unknown", raw_suffix)
        dismissed = load_dismissed_agents()
        if identity not in dismissed:
            dismissed.add(identity)
            if save_dismissed_agents(dismissed):
                sync_dismissed_agent_artifact_index(dismissed, added={identity})
    except Exception:
        pass


def _dismiss_agent_notifications(cl_name: str | None, raw_suffix: str) -> None:
    """Best-effort notification cleanup after a successful named-agent kill."""
    if not cl_name:
        return
    try:
        from sase.notifications import dismiss_notifications_matching_agents

        dismiss_notifications_matching_agents(
            [{"cl_name": cl_name, "raw_suffix": raw_suffix}]
        )
    except Exception:
        # The process is already dead (or confirmed stale), so notification
        # storage failures must not turn the successful kill into an error.
        pass


def _agent_meta_name_matches(artifacts_dir: str, expected_name: str) -> bool:
    try:
        with open(Path(artifacts_dir) / "agent_meta.json", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and data.get("name") == expected_name
