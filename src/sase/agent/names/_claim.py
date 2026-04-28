"""Enforce agent-name uniqueness across artifact directories."""

import json
from pathlib import Path


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
