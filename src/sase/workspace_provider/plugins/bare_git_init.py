"""Bare-git project initialization.

Creates new bare-repo-backed git projects, optionally from an existing bare
repository.
"""

import os
import subprocess
from pathlib import Path

from sase.workspace_provider.plugins.bare_git_ref import set_bare_repo_dir
from sase.workspace_provider.utils import set_workspace_dir


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

    set_bare_repo_dir(project_file, bare_dir)
    set_workspace_dir(project_file, clone_dir)

    return project_file
