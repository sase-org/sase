"""Agent name resolution utility for wait coordination.

Scans artifact directories across all projects to find agents by their
assigned name (via %name directive or manual TUI naming).
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _NamedAgent:
    """A named agent found in the artifacts directory."""

    name: str
    artifacts_dir: str
    is_done: bool
    outcome: str | None


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
