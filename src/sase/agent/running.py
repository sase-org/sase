"""Running agent listing and lifecycle management.

Provides functions to list currently running agents across all projects
and to kill agents by name.
"""

import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.agent.names import is_process_alive, find_named_agent
from sase.core.time import get_timezone


@dataclass
class _KillResult:
    """Result of a kill_named_agent() attempt."""

    success: bool
    message: str


@dataclass
class _RunningAgentInfo:
    """Summary info for a running agent."""

    name: str | None
    project: str
    pid: int | None
    model: str | None
    provider: str | None
    workspace_num: int | None
    duration: str
    approve: bool
    prompt: str | None = None


def list_running_agents() -> list[_RunningAgentInfo]:
    """List all currently running agents across all projects.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/`` for agents that
    have no ``done.json`` and whose process is still alive.

    Returns:
        A list of _RunningAgentInfo, sorted by start time (most recent first).
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return []

    agents: list[tuple[str, _RunningAgentInfo]] = []  # (timestamp, info)
    now = datetime.now(get_timezone())

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        project_name = project_dir.name

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            # Skip completed agents
            if (artifact_dir / "done.json").exists():
                continue

            meta_path = artifact_dir / "agent_meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            # Follow-up agents (coder/epic steps spawned after plan
            # approval) share their parent's name — skip duplicates.
            if data.get("parent_timestamp"):
                continue

            # Workflow agents with appears_as_agent=False are multi-step
            # orchestrators that shouldn't appear as separate agents.
            wf_path = artifact_dir / "workflow_state.json"
            if wf_path.exists():
                try:
                    with open(wf_path, encoding="utf-8") as f:
                        wf_data = json.load(f)
                    if isinstance(wf_data, dict) and not wf_data.get(
                        "appears_as_agent", False
                    ):
                        continue
                except (json.JSONDecodeError, OSError):
                    pass

            # Verify process is alive
            if not is_process_alive(data, artifact_dir):
                continue

            # Parse start time from directory name (YYYYmmddHHMMSS)
            ts_str = artifact_dir.name
            duration = "?"
            try:
                start = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(
                    tzinfo=get_timezone()
                )
                delta = now - start
                total_seconds = int(delta.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    duration = f"{hours}h{minutes}m"
                elif minutes > 0:
                    duration = f"{minutes}m{seconds}s"
                else:
                    duration = f"{seconds}s"
            except ValueError:
                pass

            # Resolve workspace number from RUNNING field
            workspace_num: int | None = None
            if project_name != "home":
                try:
                    from sase.running_field import get_claimed_workspaces

                    project_file = str(project_dir / f"{project_name}.gp")
                    for claim in get_claimed_workspaces(project_file):
                        if claim.artifacts_timestamp == ts_str:
                            workspace_num = claim.workspace_num
                            break
                except Exception:
                    pass

            # Read raw prompt (first ~200 chars)
            prompt_snippet: str | None = None
            raw_prompt_path = artifact_dir / "raw_xprompt.md"
            if raw_prompt_path.exists():
                try:
                    prompt_snippet = raw_prompt_path.read_text(encoding="utf-8")[
                        :200
                    ].strip()
                except OSError:
                    pass

            agents.append(
                (
                    ts_str,
                    _RunningAgentInfo(
                        name=data.get("name"),
                        project=project_name,
                        pid=data.get("pid"),
                        model=data.get("model"),
                        provider=data.get("llm_provider"),
                        workspace_num=workspace_num,
                        duration=duration,
                        approve=bool(data.get("approve")),
                        prompt=prompt_snippet,
                    ),
                )
            )

    # Sort by timestamp descending (most recent first)
    agents.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in agents]


def kill_named_agent(name: str) -> _KillResult:
    """Kill a running agent by its assigned name.

    Locates the agent via find_named_agent(), derives the project context
    from its artifacts_dir, looks up the PID, sends SIGTERM to the process
    group, and cleans up the workspace claim or running marker.

    Args:
        name: The agent name to kill.

    Returns:
        A _KillResult with success status and a human-readable message.
    """
    agent = find_named_agent(name)
    if agent is None:
        return _KillResult(False, f"No agent found with name '{name}'")

    if agent.is_done:
        outcome_str = f" ({agent.outcome})" if agent.outcome else ""
        return _KillResult(False, f"Agent '{name}' already completed{outcome_str}")

    # Derive project context from artifacts_dir
    # Format: ~/.sase/projects/{project}/artifacts/ace-run/{timestamp}/
    artifacts_path = Path(agent.artifacts_dir)
    timestamp = artifacts_path.name
    project_name = artifacts_path.parent.parent.parent.name
    project_dir = artifacts_path.parent.parent.parent
    project_file = str(project_dir / f"{project_name}.gp")

    # Find PID
    pid: int | None = None
    is_home = project_name == "home"

    if is_home:
        # Home mode: read PID from running.json
        running_json = artifacts_path / "running.json"
        if running_json.exists():
            try:
                with open(running_json, encoding="utf-8") as f:
                    data = json.load(f)
                pid = data.get("pid")
            except (json.JSONDecodeError, OSError):
                pass
    else:
        # Non-home: scan RUNNING field for matching artifacts_timestamp
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                pid = claim.pid
                break

    if pid is None:
        return _KillResult(False, f"Could not find PID for agent '{name}'")

    # Kill the process group
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Already dead — continue with cleanup
    except PermissionError:
        return _KillResult(
            False,
            f"Permission denied killing agent '{name}' (PID {pid})",
        )

    # Cleanup
    if is_home:
        # Delete running.json (idempotent with runner's own cleanup)
        running_json = artifacts_path / "running.json"
        try:
            running_json.unlink(missing_ok=True)
        except OSError:
            pass
    else:
        # Release workspace (idempotent)
        from sase.running_field import get_claimed_workspaces, release_workspace

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                release_workspace(
                    project_file, claim.workspace_num, claim.workflow, claim.cl_name
                )
                break

    return _KillResult(True, f"Killed agent '{name}' (PID {pid})")
