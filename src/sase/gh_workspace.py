"""GitHub workspace management for the #gh embedded workflow.

Provides resolution of GitHub references (repo paths, project shorthands,
and ChangeSpec names) to workspace directories, and utilities for managing
clone workspaces.

Generic utilities (``parse_workspace_dir``, ``get_default_branch``, etc.)
have been extracted to :mod:`sase.workspace_utils` and are re-exported here
for backward compatibility.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import find_all_changespecs

# Re-export generic utilities from workspace_utils for backward compat.
from sase.workspace_utils import (
    get_git_clone_dir,
    detect_vcs_type_for_project,
    ensure_git_clone,
    get_cl_field_label,
    get_default_branch,
    parse_workspace_dir,
    set_workspace_dir,
)

# Ensure re-exports are visible to static analysis and ``from sase.gh_workspace import *``.
__all__ = [
    "_ResolvedGhRef",
    "_clone_gh_repo",
    "get_git_clone_dir",
    "detect_vcs_type_for_project",
    "detect_workflow_type_for_project",
    "ensure_git_clone",
    "get_cl_field_label",
    "get_default_branch",
    "parse_workspace_dir",
    "resolve_gh_ref",
    "set_workspace_dir",
]


def _clone_gh_repo(user: str, project: str, target_dir: str) -> None:
    """Clone a GitHub repo to the target directory.

    Creates parent directories as needed. Uses SSH URL when cloning repos
    owned by the configured ``github_username`` so pushes work without
    authentication prompts.

    Raises:
        RuntimeError: If the clone fails.
    """
    from sase.github_config import get_github_username

    gh_user = get_github_username()
    if gh_user and gh_user == user:
        url = f"git@github.com:{user}/{project}.git"
    else:
        url = f"https://github.com/{user}/{project}.git"
    parent = os.path.dirname(target_dir.rstrip("/"))
    os.makedirs(parent, exist_ok=True)

    try:
        subprocess.run(
            ["git", "clone", url, target_dir.rstrip("/")],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        error_msg = f"git clone failed for {url}"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e


def detect_workflow_type_for_project(project_file: str) -> str:
    """Return ``'gh'``, ``'git'``, or ``'hg'`` based on project configuration.

    - ``'hg'``: No WORKSPACE_DIR or no ``.git`` directory.
    - ``'git'``: Has ``BARE_REPO_DIR`` set, or origin remote is a local path.
    - ``'gh'``: Git repo with a remote GitHub (or other hosted) origin.
    """
    workspace_dir = parse_workspace_dir(project_file)
    if not workspace_dir or not os.path.isdir(os.path.join(workspace_dir, ".git")):
        return "hg"

    # Lazy import to avoid circular dependency
    from sase.git_workspace import parse_bare_repo_dir

    if parse_bare_repo_dir(project_file):
        return "git"

    # Check origin remote URL — local path means bare git
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            if url and not url.startswith(("http://", "https://", "git@", "ssh://")):
                return "git"
    except Exception:
        pass

    return "gh"


@dataclass
class _ResolvedGhRef:
    """Result of resolving a ``#gh`` reference."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    checkout_target: str


def resolve_gh_ref(gh_ref: str) -> _ResolvedGhRef:
    """Resolve a ``#gh`` reference to workspace and branch information.

    Three dispatch modes:

    1. **Repo path** (contains ``/``): ``user/project`` → derive workspace from
       ``~/projects/github/<user>/<project>/``.
    2. **Project shorthand** (no ``/``, matching project dir): look up
       WORKSPACE_DIR from ``~/.sase/projects/<name>/<name>.gp``.
    3. **ChangeSpec name**: search all changespecs for a matching name,
       read WORKSPACE_DIR from its project file.

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    projects_base = Path.home() / ".sase" / "projects"

    # --- Mode 1: repo path (user/project) ---
    if "/" in gh_ref:
        parts = gh_ref.strip("/").split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid repo path '{gh_ref}': expected 'user/project'")
        user, project = parts
        primary_workspace_dir = (
            str(Path.home() / "projects" / "github" / user / project) + "/"
        )
        project_file = str(projects_base / project / f"{project}.gp")

        # Check for conflicting WORKSPACE_DIR
        existing = parse_workspace_dir(project_file)
        if existing and os.path.normpath(existing) != os.path.normpath(
            primary_workspace_dir
        ):
            raise ValueError(
                f"WORKSPACE_DIR conflict for '{project}': "
                f"existing={existing}, derived={primary_workspace_dir}"
            )

        # Clone if primary workspace doesn't exist
        if not os.path.isdir(primary_workspace_dir.rstrip("/")):
            _clone_gh_repo(user, project, primary_workspace_dir)

        set_workspace_dir(project_file, primary_workspace_dir)
        checkout_target = get_default_branch(primary_workspace_dir)

        return _ResolvedGhRef(
            project_file=project_file,
            project_name=project,
            primary_workspace_dir=primary_workspace_dir,
            checkout_target=checkout_target,
        )

    # --- Mode 2: project shorthand ---
    project_dir = projects_base / gh_ref
    project_file_path = project_dir / f"{gh_ref}.gp"
    if project_dir.is_dir() and project_file_path.exists():
        workspace_dir = parse_workspace_dir(str(project_file_path))
        if workspace_dir:
            checkout_target = get_default_branch(workspace_dir)
            return _ResolvedGhRef(
                project_file=str(project_file_path),
                project_name=gh_ref,
                primary_workspace_dir=workspace_dir,
                checkout_target=checkout_target,
            )

    # --- Mode 3: ChangeSpec name ---
    for cs in find_all_changespecs():
        if cs.name == gh_ref:
            workspace_dir = parse_workspace_dir(cs.file_path)
            if not workspace_dir:
                raise ValueError(
                    f"ChangeSpec '{gh_ref}' found in {cs.file_path} "
                    "but WORKSPACE_DIR is not set"
                )
            return _ResolvedGhRef(
                project_file=cs.file_path,
                project_name=cs.project_basename,
                primary_workspace_dir=workspace_dir,
                checkout_target=f"origin/{gh_ref}",
            )

    raise ValueError(f"Cannot resolve gh_ref '{gh_ref}'")
