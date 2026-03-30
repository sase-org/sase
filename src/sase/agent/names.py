"""Agent name resolution utility for wait coordination.

Scans artifact directories across all projects to find agents by their
assigned name (via %name directive or manual TUI naming).
"""

import itertools
import json
import os
import string
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class _AgentRefError(Exception):
    """Raised when an @name agent reference cannot be resolved."""


@dataclass
class _NamedAgent:
    """A named agent found in the artifacts directory."""

    name: str
    artifacts_dir: str
    is_done: bool
    outcome: str | None


def resolve_agent_changespec(name: str) -> str:
    """Resolve a named agent to its changespec (branch/CL name).

    Raises _AgentRefError for all failure modes.
    """
    agent = find_named_agent(name)
    if agent is None:
        raise _AgentRefError(f"No agent found with name '{name}'")
    if not agent.is_done:
        raise _AgentRefError(
            f"Agent '{name}' is still running. "
            f"Use %wait:{name} to wait for it to complete before referencing it with @{name}"
        )
    if agent.outcome != "completed":
        raise _AgentRefError(
            f"Agent '{name}' failed (outcome: {agent.outcome}). "
            f"Cannot reference a failed agent's PR with @{name}"
        )

    # Read done.json to get meta_changespec
    done_path = os.path.join(agent.artifacts_dir, "done.json")
    try:
        with open(done_path, encoding="utf-8") as f:
            done_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise _AgentRefError(
            f"Cannot read done marker for agent '{name}': {exc}"
        ) from exc

    step_output = done_data.get("step_output")
    if not step_output or not isinstance(step_output, dict):
        raise _AgentRefError(
            f"Agent '{name}' has no step output. "
            f"The agent must have run a #pr workflow to create a PR."
        )

    changespec = step_output.get("meta_changespec")
    if not changespec:
        # Legacy fallback
        meta_new_cl = step_output.get("meta_new_cl")
        if meta_new_cl:
            value = str(meta_new_cl).strip()
            paren_idx = value.rfind(" (")
            changespec = value[:paren_idx].strip() if paren_idx > 0 else value
    if not changespec:
        raise _AgentRefError(
            f"Agent '{name}' completed but did not create a PR/CL. "
            f"The agent must have run a #pr workflow to use @{name} syntax."
        )

    return str(changespec).strip()


def find_named_agent(name: str, *, only_done: bool = False) -> _NamedAgent | None:
    """Find a named agent by scanning all project artifacts.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for an agent whose ``"name"`` or ``"workflow_name"`` field matches *name*.

    Prefers running (non-done) agents over completed ones.  Exact ``name``
    matches take priority over ``workflow_name`` matches.  Among workflow
    matches, the most recent (by timestamp) is preferred.

    Args:
        name: The agent name to search for.

    Returns:
        A NamedAgent if found, or None.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return None

    best_match: _NamedAgent | None = None
    best_priority: tuple[int, str] = (0, "")

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

            if not isinstance(data, dict):
                continue

            exact = data.get("name") == name
            workflow = data.get("workflow_name") == name

            if not exact and not workflow:
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

            # Running agents take priority — return immediately,
            # but only if the process is actually alive.  Parent-phase
            # artifacts (e.g. .plan) share the agent name yet never
            # write done.json; without a liveness check we'd return
            # them as "running" and block wait resolution forever.
            # For workflow matches, only return the root agent
            # (no parent_timestamp) to avoid matching intermediate steps.
            if not is_done:
                if not only_done and is_process_alive(data, artifact_dir):
                    if exact or not data.get("parent_timestamp"):
                        return agent
                continue

            # Done agent — prefer exact matches over workflow matches,
            # and most recent timestamp within each category.
            ts = artifact_dir.name
            priority = (1 if exact else 0, ts)
            if priority > best_priority:
                best_match = agent
                best_priority = priority

    return best_match


def is_workflow_complete(name: str) -> bool | None:
    """Check whether all agents in a multi-agent workflow have completed.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for agents whose ``workflow_name`` matches *name*.

    Returns:
        ``True`` — root has ``done.json`` and no child is still alive without one.
        ``False`` — workflow exists but isn't fully complete.
        ``None`` — no agents with ``workflow_name == name`` found (not a workflow).
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return None

    # Collect all agents in this workflow
    workflow_agents: list[tuple[Path, dict[str, object]]] = []
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

            if not isinstance(data, dict):
                continue

            if data.get("workflow_name") == name:
                workflow_agents.append((artifact_dir, data))

    if not workflow_agents:
        return None

    # Find the root agent (no parent_timestamp)
    root: tuple[Path, dict[str, object]] | None = None
    children: list[tuple[Path, dict[str, object]]] = []
    for artifact_dir, meta in workflow_agents:
        if meta.get("parent_timestamp"):
            children.append((artifact_dir, meta))
        else:
            root = (artifact_dir, meta)

    if root is None:
        # No root found — the root's workflow_name may have been
        # stripped by claim_agent_name (it only preserves names on
        # artifacts with done.json, and the root may lack one).
        # Return None so the caller falls through to name-based
        # resolution via find_named_agent.
        return None

    root_dir, root_meta = root
    root_done = (root_dir / "done.json").exists()

    if not root_done:
        if is_process_alive(root_meta, root_dir):
            # Root still running — may write done.json later
            return False
        # Root is dead without done.json (crashed/killed between
        # workflow_state.json write and done.json write).  Fall through
        # to check children so the workflow can still resolve as complete
        # when all children are done/dead.
        if not children:
            return False

    # Root is done (or dead without done.json) — check all children
    for child_dir, child_meta in children:
        child_done = (child_dir / "done.json").exists()
        if not child_done and is_process_alive(child_meta, child_dir):
            # Child is still alive and hasn't finished
            return False

    return True


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

            # Don't strip names from completed agents — they need their
            # identity for #resume and historical lookups.
            if (artifact_dir / "done.json").exists():
                continue

            # Strip name from agent_meta.json
            _strip_name_from_json(artifact_dir / "agent_meta.json", name)
            # Strip name from done.json too
            _strip_name_from_json(artifact_dir / "done.json", name)


def _strip_name_from_json(path: Path, name: str) -> None:
    """Remove name-related keys from a JSON file if ``name`` or ``workflow_name`` matches.

    When ``workflow_name`` matches, both ``name`` and ``workflow_name`` are
    stripped since the child agent's name is derived from the workflow name.
    """
    try:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        changed = False
        if data.get("name") == name:
            del data["name"]
            changed = True
        if data.get("workflow_name") == name:
            data.pop("name", None)
            del data["workflow_name"]
            changed = True
        if not changed:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError, KeyError):
        pass


def get_most_recent_agent_name() -> str | None:
    """Return the name of the most recently created named agent.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for agents with a name, ordered by artifact directory timestamp
    (directory names are timestamps).

    Returns the name of the most recently created one, or ``None`` if
    no named agents exist.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return None

    candidates: list[tuple[str, str]] = []  # (dir_name, agent_name)
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

            if not isinstance(data, dict):
                continue

            name = data.get("name")
            if not name:
                continue

            candidates.append((artifact_dir.name, name))

    if not candidates:
        return None

    # Sort by directory name descending — most recent first
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def get_next_auto_name() -> str:
    """Return the lowest available alphabetic agent name.

    Scans active (non-done) agents across all projects and returns the
    first name in the sequence ``a, b, ..., z, aa, ab, ...`` that is not
    currently in use.
    """
    used = _get_active_agent_names()
    return _next_available_name(used)


def _get_active_agent_names() -> set[str]:
    """Return the set of names used by non-dismissed agents.

    An agent's name is considered in use as long as its artifact
    directory exists (dismissal deletes it).  For agents without a
    ``done.json``, we additionally verify the process is alive to
    handle orphaned agents.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return set()

    dismissed_suffixes = _load_dismissed_suffixes()
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
            if artifact_dir.name in dismissed_suffixes:
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

            # Prefer workflow_name for multi-agent workflows so the
            # base name (e.g. "a") is reserved, not the child name ("a.1").
            name = data.get("workflow_name") or data.get("name")
            if not name:
                continue

            # Follow-up agents (coder/epic steps spawned after plan
            # approval) share their parent's name and are sub-steps of
            # the parent workflow — they should not independently
            # reserve names.
            if data.get("parent_timestamp"):
                continue

            # Done agents still hold their name until dismissed
            # (dismissal deletes the artifact directory).
            done_path = artifact_dir / "done.json"
            if done_path.exists():
                names.add(name)
                continue

            # Verify the agent process is actually alive — orphaned agents
            # (killed via SIGKILL, system crash, etc.) may lack done.json
            # but their process is long dead.
            if is_process_alive(data, artifact_dir):
                names.add(name)

    return names


def _load_dismissed_suffixes() -> set[str]:
    """Return dismissed raw suffixes, ignoring load/import errors."""
    try:
        from sase.ace.dismissed_agents import load_dismissed_agents

        dismissed = load_dismissed_agents()
    except Exception:
        return set()

    return {raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None}


def is_process_alive(meta: dict[str, object], artifact_dir: Path) -> bool:
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

    # If the agent was explicitly stopped, it's dead regardless of PID state
    if meta.get("stopped_at"):
        return False

    # Delegate zombie detection to the shared helper
    from sase.ace.hooks.processes import is_process_running

    if not is_process_running(pid):
        return False

    # Guard against PID recycling: verify the process is actually a sase agent
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        if b"sase" not in cmdline and b"python" not in cmdline:
            return False
    except (FileNotFoundError, PermissionError, OSError):
        pass

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
