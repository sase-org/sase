"""Generic workspace utilities extracted from gh_workspace.py.

Provides project-file helpers (parse/set WORKSPACE_DIR), generic git
utilities (default branch, cloning), and legacy VCS-type detection that
will eventually delegate to workspace provider plugins.
"""

import os
import subprocess
from pathlib import Path

from sase.ace.changespec import (
    changespec_lock,
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
    return f"{base}_{workspace_num}/"


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


# Re-export Path for convenience (used by callers that need projects_base)
__all__ = [
    "Path",
    "ensure_git_clone",
    "get_default_branch",
    "parse_bare_repo_dir",
    "parse_workspace_dir",
    "set_workspace_dir",
]
