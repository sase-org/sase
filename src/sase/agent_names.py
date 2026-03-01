"""Agent name resolution utility for wait coordination.

Scans artifact directories across all projects to find agents by their
assigned name (via %name directive or manual TUI naming).
"""

import itertools
import json
import os
import signal
import string
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _NamedAgent:
    """A named agent found in the artifacts directory."""

    name: str
    artifacts_dir: str
    is_done: bool
    outcome: str | None


@dataclass
class _KillResult:
    """Result of a kill_named_agent() attempt."""

    success: bool
    message: str


def find_named_agent(name: str) -> _NamedAgent | None:
    """Find a named agent by scanning all project artifacts.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for an agent whose ``"name"`` field matches *name*.

    Prefers running (non-done) agents over completed ones when multiple
    matches exist.

    Args:
        name: The agent name to search for.

    Returns:
        A NamedAgent if found, or None.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return None

    best_match: _NamedAgent | None = None

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            meta_path = artifact_dir / "agent_meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict) or data.get("name") != name:
                continue

            # Found a named agent — check if it's done
            done_path = artifact_dir / "done.json"
            is_done = False
            outcome: str | None = None
            if done_path.exists():
                try:
                    with open(done_path, encoding="utf-8") as f:
                        done_data = json.load(f)
                    is_done = True
                    outcome = done_data.get("outcome")
                except (json.JSONDecodeError, OSError):
                    # done.json exists but can't be read — treat as done
                    is_done = True

            agent = _NamedAgent(
                name=name,
                artifacts_dir=str(artifact_dir),
                is_done=is_done,
                outcome=outcome,
            )

            # Running agents take priority — return immediately
            if not is_done:
                return agent

            # Otherwise, remember as fallback
            if best_match is None:
                best_match = agent

    return best_match


# pyvision: public_api_methods.txt
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


def claim_agent_name(name: str, claiming_dir: str) -> None:
    """Enforce agent name uniqueness by clearing stale name entries.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    and removes the ``"name"`` field from any file that carries *name*
    but does **not** live in *claiming_dir*.  Also strips from the
    corresponding ``done.json`` if present.

    All I/O errors are silently caught (best-effort cleanup).

    Args:
        name: The agent name being claimed.
        claiming_dir: Absolute path of the artifact directory that owns
            the name now.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    claiming = Path(claiming_dir).resolve()

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            if artifact_dir.resolve() == claiming:
                continue

            # Strip name from agent_meta.json
            _strip_name_from_json(artifact_dir / "agent_meta.json", name)
            # Strip name from done.json too
            _strip_name_from_json(artifact_dir / "done.json", name)


def _strip_name_from_json(path: Path, name: str) -> None:
    """Remove the ``"name"`` key from a JSON file if it matches *name*."""
    try:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("name") != name:
            return
        del data["name"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError, KeyError):
        pass


# pyvision: public_api_methods.txt
def get_next_auto_name() -> str:
    """Return the lowest available alphabetic agent name.

    Scans active (non-done) agents across all projects and returns the
    first name in the sequence ``a, b, ..., z, aa, ab, ...`` that is not
    currently in use.
    """
    used = _get_active_agent_names()
    return _next_available_name(used)


def _get_active_agent_names() -> set[str]:
    """Return the set of names used by currently running agents."""
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return set()

    names: set[str] = set()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            meta_path = artifact_dir / "agent_meta.json"
            if not meta_path.exists():
                continue

            # Skip agents that are done
            done_path = artifact_dir / "done.json"
            if done_path.exists():
                continue

            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            name = data.get("name")
            if not name:
                continue

            # Verify the agent process is actually alive — orphaned agents
            # (killed via SIGKILL, system crash, etc.) may lack done.json
            # but their process is long dead.
            if not _is_process_alive(data, artifact_dir):
                continue

            names.add(name)

    return names


def _is_process_alive(meta: dict[str, object], artifact_dir: Path) -> bool:
    """Check if an agent's process is still running.

    Checks the PID from ``agent_meta.json`` (preferred) or
    ``running.json`` (fallback for older home-mode agents).
    Returns ``False`` if no PID can be found or the process is dead.
    """
    pid = meta.get("pid")

    # Fallback: home-mode agents store PID in running.json
    if pid is None:
        running_path = artifact_dir / "running.json"
        if running_path.exists():
            try:
                with open(running_path, encoding="utf-8") as f:
                    running_data = json.load(f)
                pid = running_data.get("pid")
            except (json.JSONDecodeError, OSError):
                pass

    if not isinstance(pid, int):
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by another user
        return True


def _name_sequence() -> Iterator[str]:
    """Yield alphabetic names: a, b, ..., z, aa, ab, ..."""
    length = 1
    while True:
        for combo in itertools.product(string.ascii_lowercase, repeat=length):
            yield "".join(combo)
        length += 1


def _next_available_name(used: set[str]) -> str:
    """Return the first name from the alphabetic sequence not in *used*."""
    for name in _name_sequence():
        if name not in used:
            return name
    # Unreachable — infinite generator
    raise AssertionError("unreachable")
