"""Bare-git reference resolution and project-file helpers.

Contains the logic for resolving ``#git`` references to workspace and branch
information, as well as helpers for reading/writing the ``BARE_REPO_DIR`` field
in ``.gp`` project files.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import (
    changespec_lock,
    find_all_changespecs,
    write_changespec_atomic,
)
from sase.core.paths import sase_projects_dir
from sase.workspace_provider.utils import (
    get_default_branch,
    parse_bare_repo_dir,
    parse_workspace_dir,
    set_workspace_dir,
)


def set_bare_repo_dir(project_file: str, bare_repo_dir: str) -> bool:
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
class ResolvedGitRef:
    """Result of resolving a ``#git`` reference."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    bare_repo_dir: str
    checkout_target: str


def _init_missing_project_ref(project_name: str) -> ResolvedGitRef:
    """Initialize and resolve a missing project-name ``#git`` reference."""
    if not project_name:
        raise ValueError("Cannot initialize git project from empty ref")

    # Lazy import avoids a top-level cycle: bare_git_init imports
    # set_bare_repo_dir from this module.
    from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

    project_file = init_bare_git_project(project_name)
    bare_repo_dir = parse_bare_repo_dir(project_file)
    if not bare_repo_dir:
        raise RuntimeError(
            f"Initialized git project '{project_name}' at {project_file} "
            "but BARE_REPO_DIR is not set"
        )

    workspace_dir = parse_workspace_dir(project_file)
    if not workspace_dir:
        raise RuntimeError(
            f"Initialized git project '{project_name}' at {project_file} "
            "but WORKSPACE_DIR is not set"
        )

    checkout_target = get_default_branch(workspace_dir)
    return ResolvedGitRef(
        project_file=project_file,
        project_name=project_name,
        primary_workspace_dir=workspace_dir,
        bare_repo_dir=bare_repo_dir,
        checkout_target=checkout_target,
    )


def resolve_git_ref(git_ref: str) -> ResolvedGitRef:
    """Resolve a ``#git`` reference to workspace and branch information.

    Four dispatch modes:

    1. **Project shorthand** (no ``/``, matching project dir): look up
       ``BARE_REPO_DIR`` and ``WORKSPACE_DIR`` from
       ``~/.sase/projects/<name>/<name>.sase``.
    2. **ChangeSpec name**: search all changespecs for a matching name,
       verify project has ``BARE_REPO_DIR``.
    3. **Missing project shorthand**: initialize a new bare-git project using
       the same defaults as ``sase git init <name>``.
    4. **Bare repo path** (contains ``/``): derive project name from path
       basename (strip ``.git``), auto-create ``.gp`` with ``BARE_REPO_DIR``
       and ``WORKSPACE_DIR``.

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    from sase.ace.changespec.project_spec_path import (
        active_project_spec_filename,
        preferred_project_spec_path,
    )

    projects_base = sase_projects_dir()

    # --- Mode 1: project shorthand (no /) ---
    if "/" not in git_ref:
        project_dir = projects_base / git_ref
        project_file_path = Path(preferred_project_spec_path(str(project_dir), git_ref))
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
                return ResolvedGitRef(
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
                return ResolvedGitRef(
                    project_file=cs.file_path,
                    project_name=cs.project_basename,
                    primary_workspace_dir=workspace_dir,
                    bare_repo_dir=bare_repo_dir,
                    checkout_target=f"origin/{git_ref}",
                )

        return _init_missing_project_ref(git_ref)

    # --- Mode 4: bare repo path (contains /) ---
    bare_path = os.path.expanduser(git_ref)
    basename = os.path.basename(bare_path.rstrip("/"))
    project_name = basename[:-4] if basename.endswith(".git") else basename
    if not project_name:
        raise ValueError(f"Cannot derive project name from path '{git_ref}'")

    project_file = str(
        projects_base / project_name / active_project_spec_filename(project_name)
    )
    clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    set_bare_repo_dir(project_file, bare_path)
    set_workspace_dir(project_file, clone_dir)
    checkout_target = get_default_branch(clone_dir)

    return ResolvedGitRef(
        project_file=project_file,
        project_name=project_name,
        primary_workspace_dir=clone_dir,
        bare_repo_dir=bare_path,
        checkout_target=checkout_target,
    )
