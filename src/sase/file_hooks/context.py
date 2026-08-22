"""Repository and agent attribution for captured file-hook events."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase.file_hooks.models import RepoKind

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider


def current_agent_name() -> str | None:
    """Best-effort SASE agent attribution for events captured in-process."""
    try:
        from sase.agent.identity import resolve_local_agent_name

        return resolve_local_agent_name()
    except Exception:
        return None


def project_name(
    project_file: str | None,
    provider: VCSProvider | None,
    cwd: str,
) -> str:
    key: str | None = None
    if project_file:
        key = Path(project_file).expanduser().parent.name
    if key is None and provider is not None:
        try:
            ok, workspace_name = provider.get_workspace_name(cwd)
            if ok and workspace_name:
                from sase.project_aliases import resolve_project_alias_ref

                key = resolve_project_alias_ref(workspace_name)
        except Exception:
            key = None
    if key is None:
        return "unknown"
    try:
        from sase.project_display_names import project_display_name_for

        return project_display_name_for(key)
    except Exception:
        return key


def current_agent_workspace_dir() -> Path | None:
    project_dir = os.environ.get("SASE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir).expanduser().resolve(strict=False)
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        try:
            from sase.workflows.commit.commit_tracking import agent_workspace_dir

            workspace = agent_workspace_dir(artifacts_dir)
            if workspace:
                return Path(workspace).expanduser().resolve(strict=False)
        except Exception:
            pass
    return None


def classify_repository(
    repo_root: str | Path,
    *,
    sidecar_role: str | None = None,
    workspace_dir: str | Path | None = None,
) -> tuple[RepoKind, str | None]:
    """Return the repository kind and effective sidecar role."""
    root = Path(repo_root).expanduser().resolve(strict=False)
    if sidecar_role:
        return (f"sidecar:{sidecar_role}", sidecar_role)

    workspace = (
        Path(workspace_dir).expanduser().resolve(strict=False)
        if workspace_dir is not None
        else current_agent_workspace_dir()
    )
    if workspace is None or root == workspace:
        return ("primary", None)
    try:
        relative = root.relative_to(workspace / "sase" / "repos")
    except ValueError:
        return ("primary", None)
    if not relative.parts:
        return ("primary", None)
    role = relative.parts[0]
    if role == "linked":
        name = relative.parts[1] if len(relative.parts) > 1 else root.name
        return (f"linked:{name}", None)
    if role == "external":
        name = "/".join(relative.parts[1:]) or root.name
        return (f"external:{name}", None)
    return (f"sidecar:{role}", role)


__all__ = ["classify_repository", "current_agent_name", "project_name"]
