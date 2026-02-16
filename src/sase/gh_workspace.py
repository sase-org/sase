"""GitHub workspace management for the #gh embedded workflow.

Provides resolution of GitHub references (repo paths, project shorthands,
and ChangeSpec names) to workspace directories, and utilities for managing
Git worktrees.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import (
    changespec_lock,
    find_all_changespecs,
    write_changespec_atomic,
)


def _get_default_branch(workspace_dir: str) -> str:
    """Detect the default branch for the origin remote.

    Returns a string like ``"origin/main"`` or ``"origin/master"``.
    Falls back to ``"origin/main"`` on any failure.
    """
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref:
                branch = ref.rsplit("/", 1)[-1]
                return f"origin/{branch}"
    except Exception:
        pass
    return "origin/main"


def parse_workspace_dir(project_file: str) -> str | None:
    """Parse the WORKSPACE_DIR field from a .gp project file.

    Scans lines before the first ``NAME:`` line for a
    ``WORKSPACE_DIR: <path>`` entry.

    Returns:
        The expanded workspace directory path, or ``None`` if the field
        is absent, the file is missing, or the value is empty.
    """
    if not os.path.exists(project_file):
        return None

    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME:"):
                    break
                if line.startswith("WORKSPACE_DIR:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return os.path.expanduser(value)
                    return None
    except Exception:
        return None

    return None


def _set_workspace_dir(project_file: str, workspace_dir: str) -> bool:
    """Set or update the WORKSPACE_DIR field in a .gp project file.

    Creates the file and parent directories if they don't exist.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        parent_dir = os.path.dirname(project_file)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        if not os.path.exists(project_file):
            with open(project_file, "w", encoding="utf-8") as f:
                f.write(f"WORKSPACE_DIR: {workspace_dir}\n")
            return True

        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            lines = content.splitlines(keepends=True)
            new_line = f"WORKSPACE_DIR: {workspace_dir}\n"

            # Check if WORKSPACE_DIR already exists — update in place
            for i, line in enumerate(lines):
                if line.startswith("WORKSPACE_DIR:"):
                    lines[i] = new_line
                    write_changespec_atomic(
                        project_file,
                        "".join(lines),
                        f"Update WORKSPACE_DIR to {workspace_dir}",
                    )
                    return True

            # Insert before first RUNNING: or NAME: line
            insert_idx = len(lines)
            for i, line in enumerate(lines):
                if line.startswith("RUNNING:") or line.startswith("NAME:"):
                    insert_idx = i
                    break

            lines.insert(insert_idx, new_line)
            write_changespec_atomic(
                project_file,
                "".join(lines),
                f"Set WORKSPACE_DIR to {workspace_dir}",
            )
            return True
    except Exception:
        return False


def _get_git_worktree_dir(primary_workspace_dir: str, workspace_num: int) -> str:
    """Compute the path for a Git worktree.

    Args:
        primary_workspace_dir: Path to the primary (num=1) workspace.
        workspace_num: 1 for the primary workspace, 2+ for secondary worktrees.

    Returns:
        The workspace directory path (with trailing ``/``).
    """
    if workspace_num == 1:
        return primary_workspace_dir

    base = primary_workspace_dir.rstrip("/")
    return f"{base}__{workspace_num}/"


def ensure_git_worktree(primary_workspace_dir: str, workspace_num: int) -> str:
    """Ensure a Git worktree exists for the given workspace number.

    For workspace 1, verifies the primary directory exists.
    For workspace 2+, creates a detached worktree if it doesn't already exist.

    Returns:
        The worktree directory path.

    Raises:
        RuntimeError: If the directory doesn't exist (num=1) or creation fails.
    """
    worktree_dir = _get_git_worktree_dir(primary_workspace_dir, workspace_num)

    if workspace_num == 1:
        if not os.path.isdir(worktree_dir):
            raise RuntimeError(
                f"Primary workspace directory does not exist: {worktree_dir}"
            )
        return worktree_dir

    # workspace_num >= 2: create worktree if needed
    if os.path.isdir(worktree_dir):
        return worktree_dir

    # Prune stale worktrees first
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=primary_workspace_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        pass  # non-fatal

    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", worktree_dir],
            cwd=primary_workspace_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        error_msg = f"git worktree add failed (exit code {e.returncode})"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e

    return worktree_dir


def detect_vcs_type_for_project(project_file: str) -> str:
    """Detect whether a project uses Git or Mercurial.

    Returns:
        ``"git"`` if WORKSPACE_DIR is set and contains a ``.git`` directory,
        otherwise ``"hg"``.
    """
    workspace_dir = parse_workspace_dir(project_file)
    if workspace_dir and os.path.isdir(os.path.join(workspace_dir, ".git")):
        return "git"
    return "hg"


@dataclass
class ResolvedGhRef:
    """Result of resolving a ``#gh`` reference."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    branch_name: str | None
    checkout_target: str


def resolve_gh_ref(gh_ref: str) -> ResolvedGhRef:
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

        _set_workspace_dir(project_file, primary_workspace_dir)
        checkout_target = _get_default_branch(primary_workspace_dir)

        return ResolvedGhRef(
            project_file=project_file,
            project_name=project,
            primary_workspace_dir=primary_workspace_dir,
            branch_name=None,
            checkout_target=checkout_target,
        )

    # --- Mode 2: project shorthand ---
    project_dir = projects_base / gh_ref
    project_file_path = project_dir / f"{gh_ref}.gp"
    if project_dir.is_dir() and project_file_path.exists():
        workspace_dir = parse_workspace_dir(str(project_file_path))
        if workspace_dir:
            checkout_target = _get_default_branch(workspace_dir)
            return ResolvedGhRef(
                project_file=str(project_file_path),
                project_name=gh_ref,
                primary_workspace_dir=workspace_dir,
                branch_name=None,
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
            return ResolvedGhRef(
                project_file=cs.file_path,
                project_name=cs.project_basename,
                primary_workspace_dir=workspace_dir,
                branch_name=gh_ref,
                checkout_target=f"origin/{gh_ref}",
            )

    raise ValueError(f"Cannot resolve gh_ref '{gh_ref}'")
