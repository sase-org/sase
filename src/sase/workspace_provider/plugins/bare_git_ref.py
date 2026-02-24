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
from sase.workspace_utils import (
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


def resolve_git_ref(git_ref: str) -> ResolvedGitRef:
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

        raise ValueError(f"Cannot resolve git_ref '{git_ref}'")

    # --- Mode 3: bare repo path (contains /) ---
    bare_path = os.path.expanduser(git_ref)
    basename = os.path.basename(bare_path.rstrip("/"))
    project_name = basename[:-4] if basename.endswith(".git") else basename
    if not project_name:
        raise ValueError(f"Cannot derive project name from path '{git_ref}'")

    project_file = str(projects_base / project_name / f"{project_name}.gp")
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
