"""Initialize project workspace ignore rules."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import subprocess
import sys

from sase.git_lock_retry import run_with_git_lock_retry
from sase.workflows.commit.command_hooks import run_before_commit_hook

from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

LINKED_REPO_GITIGNORE_PATTERN = "/sase/repos/"
COMMAND_LABEL = "init workspace"


def find_git_root(path: Path | None = None) -> Path | None:
    # This is a read-only applicability probe; all init mutations use _run_git.
    cwd = Path.cwd() if path is None else path
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve(strict=False)


def _updated_gitignore_content(existing: str) -> str:
    lines = {line.strip() for line in existing.splitlines()}
    if LINKED_REPO_GITIGNORE_PATTERN in lines:
        return existing
    if existing:
        prefix = existing if existing.endswith("\n") else f"{existing}\n"
        return f"{prefix}{LINKED_REPO_GITIGNORE_PATTERN}\n"
    return f"{LINKED_REPO_GITIGNORE_PATTERN}\n"


def _workspace_gitignore_plan(
    project_root: Path | None = None,
) -> tuple[Path, str, str] | None:
    if not is_project_directory(project_root):
        return None
    root = find_git_root(project_root)
    if root is None:
        return None
    gitignore = root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError:
        return None
    updated = _updated_gitignore_content(existing)
    return gitignore, existing, updated


def plan_init_workspace(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for the root linked-repo ignore rule."""

    path = getattr(args, "path", None)
    project_root = Path(path).expanduser() if path is not None else None
    planned = _workspace_gitignore_plan(project_root)
    if planned is None:
        return InitPlan(
            command="workspace",
            label="Workspace",
            summary="workspace ignore rules are not applicable",
            actions=(),
        )
    gitignore, existing, updated = planned
    actions: tuple[InitAction, ...] = ()
    if updated != existing:
        actions = (
            InitAction(
                path=gitignore,
                operation="update" if gitignore.exists() else "create",
                detail="ignore host-scoped linked repository clones",
                new_content=updated,
            ),
        )
    return InitPlan(
        command="workspace",
        label="Workspace",
        summary=(
            "add /sase/repos/ to the project .gitignore"
            if actions
            else "workspace ignore rules are current"
        ),
        actions=actions,
    )


def ensure_workspace_gitignore(project_root: Path | None = None) -> Path | None:
    """Append the linked-repo clone rule and return the changed path."""

    planned = _workspace_gitignore_plan(project_root)
    if planned is None:
        return None
    gitignore, existing, updated = planned
    if updated == existing:
        return None
    gitignore.write_text(updated, encoding="utf-8")
    return gitignore


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=root,
    )
    return result


def commit_workspace_paths(
    root: Path,
    paths: Sequence[Path],
    *,
    command_label: str = COMMAND_LABEL,
    message: str = "chore: initialize SASE workspace ignores",
) -> int:
    """Commit only the project files owned by an initialization command."""

    if not run_before_commit_hook(str(root)):
        return 1
    relative = tuple(path.relative_to(root).as_posix() for path in paths)
    if not relative:
        return 0
    added = _run_git(root, "add", "--", *relative)
    if added.returncode != 0:
        print(
            f"{command_label}: git add failed: {added.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    staged = _run_git(root, "diff", "--cached", "--quiet", "--", *relative)
    if staged.returncode == 0:
        return 0
    if staged.returncode != 1:
        print(
            f"{command_label}: staged diff check failed: {staged.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    commit_message = apply_auto_commit_type_tag(message, "init")
    committed = _run_git(root, "commit", "-m", commit_message, "--", *relative)
    if committed.returncode != 0:
        print(
            f"{command_label}: commit failed: {committed.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    from ._init_chezmoi_deploy import skip_pull_push_without_upstream

    if skip_pull_push_without_upstream(root, command_label):
        return 0
    pulled = _run_git(root, "pull", "--rebase")
    if pulled.returncode != 0:
        print(
            f"{command_label}: pull failed: {pulled.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    pushed = _run_git(root, "push")
    if pushed.returncode != 0:
        print(
            f"{command_label}: push failed: {pushed.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    return 0


__all__ = [
    "LINKED_REPO_GITIGNORE_PATTERN",
    "commit_workspace_paths",
    "ensure_workspace_gitignore",
    "find_git_root",
    "plan_init_workspace",
]
