"""Record agent-name claims without mutating previous owners."""

import json
from pathlib import Path

from sase.agent.names._common import NameCollisionError
from sase.agent.names._registry import claim_registered_name, lowest_name_suggestion


def claim_agent_name(
    name: str,
    claiming_dir: str,
    *,
    explicit: bool = False,
    force_reuse: bool = False,
) -> None:
    """Record *name* for *claiming_dir*.

    Explicit ``%name:<name>`` claims reject existing owners instead of
    renaming them. Auto/retry/resume/repeat callers are expected to allocate a
    free new name before claiming; this function no longer strips or rewrites
    prior artifact metadata on their behalf.
    """
    if explicit and not force_reuse:
        _reject_explicit_collision(name, claiming_dir)
    try:
        claim_registered_name(
            name,
            claiming_dir,
            replace_existing=force_reuse or not explicit,
        )
    except NameCollisionError:
        if explicit:
            raise


def _reject_explicit_collision(name: str, claiming_dir: str) -> None:
    """Raise when *name* already belongs to another existing owner."""
    if not _name_has_existing_owner(name, Path(claiming_dir)):
        return
    suggestion = lowest_name_suggestion(name)
    raise NameCollisionError(
        f"agent name '{name}' is already taken; try '{suggestion}'"
    )


def _name_has_existing_owner(name: str, claiming_dir: Path) -> bool:
    claiming = claiming_dir.expanduser().resolve(strict=False)
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return _dismissed_bundle_name_exists(name)
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        artifacts_root = project_dir / "artifacts"
        if not artifacts_root.is_dir():
            continue

        for workflow_dir in _safe_iterdir(artifacts_root):
            if not workflow_dir.is_dir():
                continue
            for artifact_dir in _safe_iterdir(workflow_dir):
                if not artifact_dir.is_dir():
                    continue
                if artifact_dir.resolve(strict=False) == claiming:
                    continue
                if _payload_names_include(artifact_dir / "agent_meta.json", name):
                    return True
                if _payload_names_include(artifact_dir / "done.json", name):
                    return True

    return _dismissed_bundle_name_exists(name)


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _payload_names_include(path: Path, name: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("name") == name or data.get("workflow_name") == name


def _dismissed_bundle_name_exists(name: str) -> bool:
    try:
        from sase.ace.dismissed_agents import _DISMISSED_BUNDLES_DIR
    except Exception:
        return False
    try:
        paths = list(_DISMISSED_BUNDLES_DIR.rglob("*.json"))
    except OSError:
        return False
    for path in paths:
        if _payload_names_include(path, name):
            return True
    return False
