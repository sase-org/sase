"""Git workspace management for the #git embedded workflow.

Provides resolution of git references (bare repo paths, project shorthands,
and ChangeSpec names) to workspace directories, and utilities for managing
local bare-repo-backed git projects.
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
from sase.gh_workspace import (
    get_default_branch,
    set_workspace_dir,
    parse_workspace_dir,
)


def parse_bare_repo_dir(project_file: str) -> str | None:
    """Parse the BARE_REPO_DIR field from a .gp project file.

    Scans lines before the first ``NAME:`` line for a
    ``BARE_REPO_DIR: <path>`` entry.

    Returns:
        The expanded bare repo directory path, or ``None`` if the field
        is absent, the file is missing, or the value is empty.
    """
    if not os.path.exists(project_file):
        return None

    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME:"):
                    break
                if line.startswith("BARE_REPO_DIR:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return os.path.expanduser(value)
                    return None
    except Exception:
        return None

    return None


def _set_bare_repo_dir(project_file: str, bare_repo_dir: str) -> bool:
    """Set or update the BARE_REPO_DIR field in a .gp project file.

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
                f.write(f"BARE_REPO_DIR: {bare_repo_dir}\n")
            return True

        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            lines = content.splitlines(keepends=True)
            new_line = f"BARE_REPO_DIR: {bare_repo_dir}\n"

            # Check if BARE_REPO_DIR already exists — update in place
            for i, line in enumerate(lines):
                if line.startswith("BARE_REPO_DIR:"):
                    lines[i] = new_line
                    write_changespec_atomic(
                        project_file,
                        "".join(lines),
                        f"Update BARE_REPO_DIR to {bare_repo_dir}",
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
                f"Set BARE_REPO_DIR to {bare_repo_dir}",
            )
            return True
    except Exception:
        return False


@dataclass
class _ResolvedGitRef:
    """Result of resolving a ``#git`` reference."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    bare_repo_dir: str
    checkout_target: str


def resolve_git_ref(git_ref: str) -> _ResolvedGitRef:
    """Resolve a ``#git`` reference to workspace and branch information.

    Three dispatch modes:

    1. **Project shorthand** (no ``/``, matching project dir): look up
       ``BARE_REPO_DIR`` and ``WORKSPACE_DIR`` from
       ``~/.sase/projects/<name>/<name>.gp``.
    2. **ChangeSpec name**: search all changespecs for a matching name,
       verify project has ``BARE_REPO_DIR``.
    3. **Bare repo path** (contains ``/``): derive project name from path
       basename (strip ``.git``), auto-create ``.gp`` with ``BARE_REPO_DIR``
       and ``WORKSPACE_DIR``.

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    projects_base = Path.home() / ".sase" / "projects"

    # --- Mode 1: project shorthand (no /) ---
    if "/" not in git_ref:
        project_dir = projects_base / git_ref
        project_file_path = project_dir / f"{git_ref}.gp"
        if project_dir.is_dir() and project_file_path.exists():
            bare_repo_dir = parse_bare_repo_dir(str(project_file_path))
            if bare_repo_dir:
                workspace_dir = parse_workspace_dir(str(project_file_path))
                if not workspace_dir:
                    raise ValueError(
                        f"Project '{git_ref}' has BARE_REPO_DIR but "
                        "WORKSPACE_DIR is not set"
                    )
                checkout_target = get_default_branch(workspace_dir)
                return _ResolvedGitRef(
                    project_file=str(project_file_path),
                    project_name=git_ref,
                    primary_workspace_dir=workspace_dir,
                    bare_repo_dir=bare_repo_dir,
                    checkout_target=checkout_target,
                )

        # --- Mode 2: ChangeSpec name ---
        for cs in find_all_changespecs():
            if cs.name == git_ref:
                bare_repo_dir = parse_bare_repo_dir(cs.file_path)
                if not bare_repo_dir:
                    raise ValueError(
                        f"ChangeSpec '{git_ref}' found in {cs.file_path} "
                        "but BARE_REPO_DIR is not set"
                    )
                workspace_dir = parse_workspace_dir(cs.file_path)
                if not workspace_dir:
                    raise ValueError(
                        f"ChangeSpec '{git_ref}' found in {cs.file_path} "
                        "but WORKSPACE_DIR is not set"
                    )
                return _ResolvedGitRef(
                    project_file=cs.file_path,
                    project_name=cs.project_basename,
                    primary_workspace_dir=workspace_dir,
                    bare_repo_dir=bare_repo_dir,
                    checkout_target=f"origin/{git_ref}",
                )

        raise ValueError(f"Cannot resolve git_ref '{git_ref}'")

    # --- Mode 3: bare repo path (contains /) ---
    bare_path = os.path.expanduser(git_ref)
    basename = os.path.basename(bare_path.rstrip("/"))
    project_name = basename[:-4] if basename.endswith(".git") else basename
    if not project_name:
        raise ValueError(f"Cannot derive project name from path '{git_ref}'")

    project_file = str(projects_base / project_name / f"{project_name}.gp")
    clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    _set_bare_repo_dir(project_file, bare_path)
    set_workspace_dir(project_file, clone_dir)
    checkout_target = get_default_branch(clone_dir)

    return _ResolvedGitRef(
        project_file=project_file,
        project_name=project_name,
        primary_workspace_dir=clone_dir,
        bare_repo_dir=bare_path,
        checkout_target=checkout_target,
    )


def init_bare_git_project(
    project_name: str,
    *,
    bare_dir: str | None = None,
    clone_dir: str | None = None,
    existing_bare: str | None = None,
) -> str:
    """Initialize a new bare-repo-backed git project.

    Args:
        project_name: Name of the project.
        bare_dir: Path for the bare repo. Defaults to
            ``~/.sase/repos/<name>.git``.
        clone_dir: Path for the working clone. Defaults to
            ``~/projects/git/<name>/``.
        existing_bare: Path to an existing bare repo to clone from
            instead of creating a new one.

    Returns:
        The path to the created ``.gp`` project file.

    Raises:
        RuntimeError: If git commands fail or existing_bare is not a bare repo.
    """
    if bare_dir is None:
        bare_dir = str(Path.home() / ".sase" / "repos" / f"{project_name}.git")
    if clone_dir is None:
        clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    if existing_bare:
        # Validate it's a bare repo (use --git-dir to avoid
        # safe.bareRepository=explicit blocking access)
        result = subprocess.run(
            ["git", "--git-dir", existing_bare, "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise RuntimeError(f"'{existing_bare}' is not a valid bare git repository")
        bare_dir = existing_bare

        # Clone from existing bare
        subprocess.run(
            ["git", "clone", bare_dir, clone_dir],
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        # Create new bare repo
        os.makedirs(bare_dir, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", bare_dir],
            capture_output=True,
            text=True,
            check=True,
        )

        # Clone it (will be empty)
        subprocess.run(
            ["git", "clone", bare_dir, clone_dir],
            capture_output=True,
            text=True,
            check=True,
        )

        # Set default git identity for the initial commit
        subprocess.run(
            ["git", "config", "user.email", "sase@localhost"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "sase"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )

        # Create initial commit and push
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )

    # Create .gp project file
    projects_base = Path.home() / ".sase" / "projects"
    project_file = str(projects_base / project_name / f"{project_name}.gp")

    _set_bare_repo_dir(project_file, bare_dir)
    set_workspace_dir(project_file, clone_dir)

    return project_file
