"""Resolve a finalizer run's storage project key from its host bindings."""

from __future__ import annotations

import os
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name, sase_projects_dir


def resolve_finalizer_project_key(root: Path) -> str | None:
    """Prefer the run's artifact owner, then its project file, then its checkout."""
    try:
        relative = (
            root.expanduser().resolve().relative_to(sase_projects_dir().resolve())
        )
        if len(relative.parts) > 1 and relative.parts[1] == "artifacts":
            return relative.parts[0]
    except (OSError, RuntimeError, ValueError):
        pass
    project_file = (os.environ.get("SASE_AGENT_PROJECT_FILE") or "").strip()
    if project_file:
        parent = Path(project_file).expanduser().resolve().parent.name
        if is_valid_sase_project_name(parent):
            return parent
    try:
        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.llm_provider.commit_finalizer_config import (
            resolve_finalizer_project_dir,
        )
        from sase.project_aliases import resolve_project_alias_ref
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(resolve_finalizer_project_dir())
        if found is None:
            return None
        name = found[1].project_name.strip()
        if not name or not is_valid_sase_project_name(name):
            return None
        project = resolve_project_alias_ref(name) or name
        if not is_valid_sase_project_name(project):
            return None
        spec = Path(
            preferred_project_spec_path(str(sase_projects_dir() / project), project)
        )
        return project if spec.is_file() else None
    except Exception:
        return None


__all__ = ["resolve_finalizer_project_key"]
