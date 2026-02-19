"""GitHub workspace management for the #gh embedded workflow.

Provides resolution of GitHub references (repo paths, project shorthands,
and ChangeSpec names) to workspace directories, and utilities for managing
clone workspaces.
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


def get_default_branch(workspace_dir: str) -> str:
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


def _clone_gh_repo(user: str, project: str, target_dir: str) -> None:
    """Clone a GitHub repo to the target directory.

    Creates parent directories as needed.

    Raises:
        RuntimeError: If the clone fails.
    """
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


def set_workspace_dir(project_file: str, workspace_dir: str) -> bool:
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


def _get_git_clone_dir(primary_workspace_dir: str, workspace_num: int) -> str:
    """Compute the path for a Git clone workspace.

    Args:
        primary_workspace_dir: Path to the primary (num=1) workspace.
        workspace_num: 1 for the primary workspace, 2+ for secondary clones.

    Returns:
        The workspace directory path (with trailing ``/``).
    """
    if workspace_num == 1:
        return primary_workspace_dir

    base = primary_workspace_dir.rstrip("/")
    return f"{base}__{workspace_num}/"


def ensure_git_clone(primary_workspace_dir: str, workspace_num: int) -> str:
    """Ensure a Git clone workspace exists for the given workspace number.

    For workspace 1, verifies the primary directory exists.
    For workspace 2+, creates an independent clone of the primary workspace
    if it doesn't already exist. Clones are local (hard-linked objects) and
    have their origin re-pointed to the real remote URL.

    Returns:
        The clone directory path.

    Raises:
        RuntimeError: If the directory doesn't exist (num=1) or creation fails.
    """
    clone_dir = _get_git_clone_dir(primary_workspace_dir, workspace_num)

    if workspace_num == 1:
        if not os.path.isdir(clone_dir):
            raise RuntimeError(
                f"Primary workspace directory does not exist: {clone_dir}"
            )
        return clone_dir

    # workspace_num >= 2: create clone if needed
    if os.path.isdir(clone_dir):
        # Validate existing clone with git status
        result = subprocess.run(
            ["git", "status"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return clone_dir
        # Stale/corrupt clone — remove and re-create
        import shutil

        shutil.rmtree(clone_dir.rstrip("/"), ignore_errors=True)

    if not os.path.isdir(primary_workspace_dir.rstrip("/")):
        raise RuntimeError(
            f"Primary workspace directory does not exist: {primary_workspace_dir}"
        )

    # Get the real remote URL from the primary workspace
    url_result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=primary_workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    real_url = url_result.stdout.strip() if url_result.returncode == 0 else ""

    try:
        subprocess.run(
            ["git", "clone", primary_workspace_dir.rstrip("/"), clone_dir.rstrip("/")],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Race-condition guard: another process may have created the clone
        if os.path.isdir(clone_dir):
            check = subprocess.run(
                ["git", "status"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if check.returncode == 0:
                return clone_dir
        error_msg = f"git clone failed (exit code {e.returncode})"
        if e.stderr:
            error_msg += f": {e.stderr.strip()}"
        raise RuntimeError(error_msg) from e

    # Re-point origin to the real remote URL
    if real_url:
        subprocess.run(
            ["git", "remote", "set-url", "origin", real_url],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    # Sync refs from the real remote
    subprocess.run(
        ["git", "fetch", "--quiet"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    return clone_dir


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


def get_cl_field_label(project_file: str) -> str:
    """Return 'PR' for git projects, 'CL' for hg projects."""
    return "PR" if detect_vcs_type_for_project(project_file) == "git" else "CL"


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
    branch_name: str | None
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
            branch_name=None,
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
            return _ResolvedGhRef(
                project_file=cs.file_path,
                project_name=cs.project_basename,
                primary_workspace_dir=workspace_dir,
                branch_name=gh_ref,
                checkout_target=f"origin/{gh_ref}",
            )

    raise ValueError(f"Cannot resolve gh_ref '{gh_ref}'")
